"""Turn an uploaded document into searchable passages and queryable tables.

Runs in the worker, never in a request. The extraction and chunking rules
are the measured ones in ``app.services`` and are reused unchanged; this
module adds what a multi-user service needs around them:

**All or nothing.** Passages, embeddings, tables and the ``ready`` status are
written in one transaction. A failure leaves the document ``failed`` with a
reason a person can read, and no partial passages behind it.

**Deletion wins.** A document deleted while it is being indexed is not
brought back: the final write re-checks the row under a lock first.

**Embedding is batched** with one model per process, loaded once.
"""

import datetime as dt
import hashlib
import json
import logging
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Document, DocumentTable, Passage
from app.ingest.storage import LocalFileStorage
from app.services.dense_retriever import embedding_input, load_encoder
from app.services.document_extraction import DocumentExtractionError
from app.services.document_ingestion import (
    DocumentIngestionError,
    extract_pages,
    passage_title,
)
from app.services.table_store import read_sheets
from app.services.text_chunking import chunk_pages

logger = logging.getLogger(__name__)

EMBED_BATCH = 64
TABLE_KINDS = {".csv", ".xlsx"}


class IngestionFailed(Exception):
    """A failure whose message is fit to show the person who uploaded the file."""


def index_document(
    db: Session,
    document_id: uuid.UUID,
    storage: LocalFileStorage,
    settings: Settings | None = None,
) -> str:
    """Index one document. Returns its final status.

    Never raises for a bad file: that is recorded on the document. Raises only
    for infrastructure failures (database down), which the queue retries.
    """
    settings = settings or get_settings()
    document = db.get(Document, document_id)
    if document is None:
        return "deleted"
    if document.status == "ready":
        return "ready"
    document.status, document.error = "indexing", None
    db.commit()

    try:
        passages, tables, page_count = _build(document, storage, settings)
    except IngestionFailed as exc:
        return _fail(db, document_id, str(exc))
    except Exception:  # noqa: BLE001 - recorded, then reported generically
        logger.exception("Indexing %s failed unexpectedly", document_id)
        return _fail(
            db,
            document_id,
            "Indexing failed unexpectedly. Try uploading the file again.",
        )

    # Re-read under a lock: if the document was deleted meanwhile, stop.
    current = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if current is None:
        db.rollback()
        return "deleted"
    db.execute(delete(Passage).where(Passage.document_id == document_id))
    db.execute(delete(DocumentTable).where(DocumentTable.document_id == document_id))
    db.add_all(passages)
    db.add_all(tables)
    current.status = "ready"
    current.error = None
    current.page_count = page_count
    current.passage_count = len(passages)
    current.indexed_at = dt.datetime.now(dt.UTC)
    db.commit()
    logger.info(
        "Indexed %s: %d passages, %d tables", document_id, len(passages), len(tables)
    )
    return "ready"


def _build(
    document: Document, storage: LocalFileStorage, settings: Settings
) -> tuple[list[Passage], list[DocumentTable], int | None]:
    path = storage.path(document.storage_key)
    if not path.is_file():
        raise IngestionFailed("The uploaded file is missing. Upload it again.")
    try:
        pages = extract_pages(
            path,
            document.kind,
            redact=settings.redact_contact_details,
            ocr=settings.ocr_enabled,
        )
    except (DocumentExtractionError, DocumentIngestionError) as exc:
        raise IngestionFailed(str(exc)) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestionFailed(
            f"{document.filename} could not be read: {exc.__class__.__name__}."
        ) from exc

    chunks = chunk_pages(pages, merge_pages=document.kind == ".pdf")
    if not chunks:
        raise IngestionFailed(f"{document.filename} contains no readable text.")

    stem = Path(document.filename).stem
    titles = [passage_title(stem, chunk.heading) for chunk in chunks]
    vectors = _embed(
        [embedding_input(t, c.text) for t, c in zip(titles, chunks, strict=True)],
        settings,
    )
    passages = [
        Passage(
            workspace_id=document.workspace_id,
            document_id=document.id,
            ordinal=index,
            page=chunk.page,
            heading=chunk.heading,
            title=title,
            text=chunk.text,
            text_hash=hashlib.sha1(chunk.text.encode()).hexdigest(),
            embedding=vector,
        )
        for index, (chunk, title, vector) in enumerate(
            zip(chunks, titles, vectors, strict=True)
        )
    ]
    tables = []
    if document.kind in TABLE_KINDS:
        for sheet, rows in read_sheets(path):
            if len(rows) >= 2:
                safe = [[_json_cell(cell) for cell in row] for row in rows]
                tables.append(
                    DocumentTable(
                        workspace_id=document.workspace_id,
                        document_id=document.id,
                        sheet=sheet,
                        rows=safe,
                        row_count=len(safe) - 1,
                    )
                )
    pages_seen = [p.page for p in pages if p.page]
    page_count = max(pages_seen) if pages_seen and document.kind == ".pdf" else None
    return passages, tables, page_count


def _embed(texts: list[str], settings: Settings) -> list[list[float]]:
    encoder = load_encoder(settings.dense_model)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = encoder.encode(
            texts[start : start + EMBED_BATCH], normalize_embeddings=True
        )
        vectors.extend([float(x) for x in row] for row in batch)
    return vectors


def _json_cell(value):
    """A spreadsheet cell as something JSON can hold."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    return str(value)


def _fail(db: Session, document_id: uuid.UUID, message: str) -> str:
    db.rollback()
    document = db.get(Document, document_id)
    if document is None:
        return "deleted"
    document.status = "failed"
    document.error = message[:1000]
    db.commit()
    logger.info("Indexing %s failed: %s", document_id, message)
    return "failed"
