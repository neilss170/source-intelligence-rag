"""Retrieval over one workspace's passages in Postgres.

The measured pipeline - keyword and vector candidates fused by reciprocal
rank, then cross-encoder reranking - is reused as it is
(``HybridRetriever`` and ``CrossEncoderReranker``). This module only supplies
the two candidate sources, now backed by the database instead of memory:

- **Keyword:** the passage ``tsv`` column (title weighted over body). The
  question's words are OR-ed, not AND-ed, so a passage need not contain every
  word of a natural-language question; exact identifiers such as ``SH-0042``
  survive as lexemes and still match.
- **Vector:** cosine distance on the HNSW index, with pgvector's iterative
  scan so filtering to one workspace never starves the result list.

Every query filters on ``workspace_id``; no other workspace's passage can be
returned.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.resume import EvidenceUnit, ResumeSection, SourceReference
from app.services.cross_encoder_reranker import CrossEncoderReranker
from app.services.dense_retriever import load_encoder
from app.services.hybrid_retriever import HybridRetriever
from app.services.llm_generator import PASSAGE_MAX_CHARS
from app.services.table_store import TableStore

_COLUMNS = """
    p.id, p.document_id, p.title, p.text, p.page, d.filename
"""

#: Candidates the HNSW scan examines; higher is more accurate and slower.
EF_SEARCH = 100


@dataclass(frozen=True, slots=True)
class ScoredPassage:
    evidence: EvidenceUnit
    score: float


def _evidence(row) -> EvidenceUnit:
    return EvidenceUnit(
        evidence_id=f"ev_{row.id.hex}",
        section=ResumeSection.DOCUMENT,
        title=row.title,
        text=row.text,
        source=SourceReference(
            document_id=str(row.document_id),
            filename=row.filename,
            page=row.page,
            source_text=row.text,
        ),
    )


class PgKeywordRetriever:
    def __init__(self, db: Session, workspace_id: uuid.UUID) -> None:
        self._db = db
        self._workspace_id = workspace_id

    def search(self, query: str, *, top_k: int = 20) -> list[ScoredPassage]:
        rows = self._db.execute(
            text(
                f"""
                WITH q AS (
                    SELECT to_tsquery(
                        'simple',
                        string_agg(quote_literal(lexeme), ' | ')
                    ) AS query
                    FROM unnest(
                        tsvector_to_array(to_tsvector('english', :question))
                    ) AS lexeme
                )
                SELECT {_COLUMNS}, ts_rank_cd(p.tsv, q.query, 32) AS score
                FROM passages p
                JOIN documents d ON d.id = p.document_id, q
                WHERE p.workspace_id = :workspace
                  AND q.query IS NOT NULL
                  AND p.tsv @@ q.query
                ORDER BY score DESC, p.id
                LIMIT :limit
                """
            ),
            {"question": query, "workspace": self._workspace_id, "limit": top_k},
        )
        return [ScoredPassage(_evidence(row), float(row.score)) for row in rows]


class PgDenseRetriever:
    def __init__(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        *,
        model_name: str,
        minimum_score: float,
    ) -> None:
        self._db = db
        self._workspace_id = workspace_id
        self._model_name = model_name
        self._minimum_score = minimum_score

    def search(self, query: str, *, top_k: int = 20) -> list[ScoredPassage]:
        if not query.strip():
            return []
        vector = load_encoder(self._model_name).encode(
            [query], prompt_name="query", normalize_embeddings=True
        )[0]
        literal = "[" + ",".join(f"{float(x):.7f}" for x in vector) + "]"
        # Filtering an HNSW scan to one workspace can leave too few rows;
        # iterative scanning keeps going until the limit is met.
        self._db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        self._db.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
        rows = self._db.execute(
            text(
                f"""
                SELECT {_COLUMNS},
                       1 - (p.embedding <=> CAST(:vector AS vector)) AS score
                FROM passages p
                JOIN documents d ON d.id = p.document_id
                WHERE p.workspace_id = :workspace
                ORDER BY p.embedding <=> CAST(:vector AS vector)
                LIMIT :limit
                """
            ),
            {"vector": literal, "workspace": self._workspace_id, "limit": top_k},
        )
        hits = [ScoredPassage(_evidence(row), float(row.score)) for row in rows]
        # relaxed_order may return near-ties slightly out of order.
        hits.sort(key=lambda hit: -hit.score)
        return [hit for hit in hits if hit.score >= self._minimum_score]


def workspace_retriever(
    db: Session, workspace_id: uuid.UUID, settings: Settings
) -> CrossEncoderReranker:
    """The measured retrieval chain, over one workspace in Postgres."""
    candidates = settings.retrieval_candidates
    return CrossEncoderReranker(
        HybridRetriever(
            PgKeywordRetriever(db, workspace_id),
            PgDenseRetriever(
                db,
                workspace_id,
                model_name=settings.dense_model,
                minimum_score=settings.dense_min_score,
            ),
            candidate_k=candidates,
        ),
        model_name=settings.reranker_model,
        candidate_k=candidates,
        probabilities=True,
        min_score=settings.rerank_min_probability,
        min_keep=settings.rerank_min_keep,
    )


def workspace_size(db: Session, workspace_id: uuid.UUID) -> int:
    """Passage characters as the prompt would count them."""
    return int(
        db.execute(
            text(
                "SELECT coalesce(sum(least(length(text), :cap)), 0) "
                "FROM passages WHERE workspace_id = :workspace"
            ),
            {"cap": PASSAGE_MAX_CHARS, "workspace": workspace_id},
        ).scalar_one()
    )


def workspace_passages(db: Session, workspace_id: uuid.UUID) -> list[EvidenceUnit]:
    """Every passage of the workspace, in upload and reading order."""
    rows = db.execute(
        text(
            f"""
            SELECT {_COLUMNS}
            FROM passages p
            JOIN documents d ON d.id = p.document_id
            WHERE p.workspace_id = :workspace
            ORDER BY d.created_at, d.id, p.ordinal
            """
        ),
        {"workspace": workspace_id},
    )
    return [_evidence(row) for row in rows]


@dataclass(frozen=True, slots=True)
class FileSummary:
    filename: str
    passage_count: int
    page_count: int | None
    status: str


def workspace_files(db: Session, workspace_id: uuid.UUID) -> list[FileSummary]:
    """The overview the model always gets: what is uploaded, without the text."""
    rows = db.execute(
        text(
            "SELECT filename, passage_count, page_count, status FROM documents "
            "WHERE workspace_id = :workspace ORDER BY created_at, id"
        ),
        {"workspace": workspace_id},
    )
    return [
        FileSummary(r.filename, r.passage_count, r.page_count, r.status) for r in rows
    ]


def workspace_tables(db: Session, workspace_id: uuid.UUID) -> TableStore:
    """The workspace's spreadsheets as a locked-down SQLite store."""
    rows = db.execute(
        text(
            """
            SELECT t.document_id, d.filename, t.sheet, t.rows
            FROM document_tables t
            JOIN documents d ON d.id = t.document_id
            WHERE t.workspace_id = :workspace AND d.status = 'ready'
            ORDER BY d.created_at, t.sheet
            """
        ),
        {"workspace": workspace_id},
    )
    return TableStore.from_sheets(
        [(str(r.document_id), r.filename, r.sheet, r.rows) for r in rows]
    )
