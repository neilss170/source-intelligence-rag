import hashlib
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import Caller, current_caller
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import limit_uploads
from app.db import repository
from app.db.models import Document
from app.db.session import get_db
from app.ingest.queue import IngestionQueue, get_queue
from app.ingest.storage import LocalFileStorage, get_storage
from app.ingest.validation import detect_kind
from app.services.document_ingestion import safe_filename

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])

READ_CHUNK = 1024 * 1024


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    kind: str
    size_bytes: int
    status: str
    error: str | None
    page_count: int | None
    passage_count: int
    created_at: datetime
    indexed_at: datetime | None
    #: True when these exact bytes were already uploaded to this workspace.
    duplicate: bool = False


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    caller: Caller = Depends(current_caller), db: Session = Depends(get_db)
) -> list[DocumentOut]:
    return [
        DocumentOut.model_validate(d)
        for d in repository.list_documents(db, caller.workspace.id)
    ]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
) -> DocumentOut:
    return DocumentOut.model_validate(
        repository.get_document(db, caller.workspace.id, document_id)
    )


@router.post(
    "/documents",
    response_model=list[DocumentOut],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_documents(
    files: list[UploadFile] = File(...),
    caller: Caller = Depends(limit_uploads),
    db: Session = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    queue: IngestionQueue = Depends(get_queue),
) -> list[DocumentOut]:
    """Accept files for indexing. Indexing happens in the background; poll
    ``GET /documents/{id}`` (or the list) until ``status`` is ``ready``."""
    settings = get_settings()
    if not files:
        raise AppError(422, "no_files", "Choose at least one file to upload.")
    if len(files) > settings.max_upload_files:
        raise AppError(
            413,
            "too_many_files",
            f"Upload at most {settings.max_upload_files} files at a time.",
        )

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    received: list[tuple[str, str, bytes]] = []
    for upload in files:
        name = safe_filename(upload.filename or "document")
        content = await _read_limited(
            upload, max_bytes, name, settings.max_file_size_mb
        )
        if not content:
            raise AppError(422, "empty_file", f"{name} is empty.")
        received.append((name, detect_kind(name, content), content))

    used = repository.workspace_bytes(db, caller.workspace.id)
    incoming = sum(len(content) for _, _, content in received)
    if used + incoming > settings.max_workspace_mb * 1024 * 1024:
        raise AppError(
            413,
            "workspace_full",
            f"This would take your workspace over {settings.max_workspace_mb} MB. "
            "Delete some documents first.",
        )

    results: list[DocumentOut] = []
    queued: list[uuid.UUID] = []
    for name, kind, content in received:
        checksum = hashlib.sha256(content).hexdigest()
        existing = repository.find_document_by_checksum(
            db, caller.workspace.id, checksum
        )
        if existing is not None:
            out = DocumentOut.model_validate(existing)
            results.append(out.model_copy(update={"duplicate": True}))
            continue
        key = storage.put(content, kind)
        document = Document(
            workspace_id=caller.workspace.id,
            filename=name,
            kind=kind,
            size_bytes=len(content),
            checksum=checksum,
            storage_key=key,
            status="uploaded",
        )
        try:
            # A savepoint per file: a conflict here must not undo the files
            # already accepted earlier in this request.
            with db.begin_nested():
                db.add(document)
                db.flush()
        except IntegrityError:
            # The same file twice in one request, or a concurrent upload.
            storage.delete(key)
            existing = repository.find_document_by_checksum(
                db, caller.workspace.id, checksum
            )
            if existing is None:
                raise
            out = DocumentOut.model_validate(existing)
            results.append(out.model_copy(update={"duplicate": True}))
            continue
        db.refresh(document)
        results.append(DocumentOut.model_validate(document))
        queued.append(document.id)
    db.commit()

    for document_id in queued:
        try:
            await queue.enqueue(document_id)
        except Exception:  # noqa: BLE001 - the worker's sweep re-queues it
            logger.exception("Could not queue %s; the worker sweep will", document_id)
    return results


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> Response:
    key = repository.delete_document(db, caller.workspace.id, document_id)
    db.commit()
    storage.delete(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _read_limited(
    upload: UploadFile, max_bytes: int, name: str, max_mb: int
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(READ_CHUNK):
        size += len(chunk)
        if size > max_bytes:
            raise AppError(413, "file_too_large", f"{name} is larger than {max_mb} MB.")
        chunks.append(chunk)
    return b"".join(chunks)
