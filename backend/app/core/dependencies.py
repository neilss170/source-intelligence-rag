from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.models.resume import EvidenceUnit
from app.services.adaptive_retriever import AdaptiveTopKRetriever
from app.services.bm25_retriever import BM25Retriever
from app.services.citation_support import SupportVerifier
from app.services.cross_encoder_reranker import CrossEncoderReranker
from app.services.dense_retriever import DenseRetriever
from app.services.document_ingestion import DocumentIngestionService
from app.services.entity_guard import EntityGuardRetriever
from app.services.general_knowledge import LocalGeneralKnowledgeProvider
from app.services.grounded_generator import GroundedGenerator
from app.services.hybrid_retriever import HybridRetriever
from app.services.llm_client import ChatCompletionClient
from app.services.llm_generator import LLMGroundedGenerator
from app.services.query_service import QueryService
from app.services.routed_retriever import RoutedDenseRetriever
from app.services.table_store import TableStore
from app.services.uploaded_evidence_repository import UploadedEvidenceRepository
from app.services.web_search import TavilySearchProvider

TABLE_EXTENSIONS = {".csv", ".xlsx"}


def build_retriever(
    evidence: list[EvidenceUnit],
    settings: Settings,
    *,
    model_backed: bool,
    cache_dir: Path | None = None,
):
    """The retrieval chain for ``evidence``.

    With a model writing answers: BM25 and dense search fused by reciprocal
    rank, then cross-encoder reranking, keeping however many passages were
    asked for. BM25 catches exact strings - IDs, codes, names, figures - that
    embeddings blur; the reranker orders the union.

    Without one, the rule-based generator expects the original chain: section
    routing, the entity guard and adaptive top-k were all tuned for it.
    """
    cache_path = cache_dir / "embeddings.npz" if cache_dir else None
    if model_backed:
        candidates = settings.retrieval_candidates
        return CrossEncoderReranker(
            HybridRetriever(
                BM25Retriever(evidence),
                DenseRetriever(
                    evidence,
                    model_name=settings.dense_model,
                    minimum_score=settings.dense_min_score,
                    cache_path=cache_path,
                ),
                candidate_k=candidates,
            ),
            model_name=settings.reranker_model,
            candidate_k=candidates,
            probabilities=True,
            min_score=settings.rerank_min_probability,
            min_keep=settings.rerank_min_keep,
        )
    retriever = EntityGuardRetriever(
        RoutedDenseRetriever(
            DenseRetriever(
                evidence,
                model_name=settings.dense_model,
                minimum_score=0.35,
                cache_path=cache_path,
            )
        ),
        evidence,
    )
    if settings.reranker_enabled:
        retriever = CrossEncoderReranker(retriever, model_name=settings.reranker_model)
    return AdaptiveTopKRetriever(retriever)


def build_table_store(evidence: list[EvidenceUnit], uploads_dir: Path) -> TableStore:
    files = []
    seen = set()
    for item in evidence:
        source = item.source
        if source.document_id in seen:
            continue
        seen.add(source.document_id)
        if Path(source.filename).suffix.lower() not in TABLE_EXTENSIONS:
            continue
        path = uploads_dir / f"{source.document_id}_{source.filename}"
        if path.is_file():
            files.append((source.document_id, source.filename, path))
    return TableStore(files)


@lru_cache
def chat_client(
    api_key: str, api_base_url: str, model: str, fallback_models: tuple[str, ...]
) -> ChatCompletionClient:
    """One client per configuration, kept across uploads.

    The client remembers which models have run out of quota; rebuilding it on
    every upload would forget, and spend a request rediscovering it.
    """
    return ChatCompletionClient(
        api_key=api_key,
        api_base_url=api_base_url,
        model=model,
        fallback_models=fallback_models,
    )


def build_query_service(
    evidence: list[EvidenceUnit],
    settings: Settings,
    *,
    uploads_dir: Path,
    cache_dir: Path | None = None,
    client: ChatCompletionClient | None = None,
) -> QueryService:
    model_backed = bool(settings.chat_api_key and settings.llm_answers_enabled)
    retriever = (
        build_retriever(
            evidence, settings, model_backed=model_backed, cache_dir=cache_dir
        )
        if evidence
        else None
    )
    generator = GroundedGenerator()
    verifier = None
    if model_backed:
        client = client or chat_client(
            settings.chat_api_key,
            settings.chat_api_base_url,
            settings.chat_model,
            settings.fallback_models,
        )
        generator = LLMGroundedGenerator(
            client,
            fallback=generator,
            workspace=evidence,
            budget=settings.workspace_context_chars,
            ranker=retriever,
            tables=(
                build_table_store(evidence, uploads_dir)
                if settings.table_queries_enabled
                else None
            ),
        )
        if settings.verify_citations:
            verifier = SupportVerifier(
                settings.nli_model, threshold=settings.support_threshold
            )
    return QueryService(
        retriever,
        generator,
        LocalGeneralKnowledgeProvider(
            api_key=settings.chat_api_key,
            api_base_url=settings.chat_api_base_url,
            chat_model=settings.chat_model,
            local_model=settings.local_chat_model,
            client=client,
        ),
        TavilySearchProvider(
            settings.tavily_api_key if settings.web_search_enabled else None,
            country=settings.search_country,
            max_results=settings.search_max_results,
        ),
        verifier=verifier,
        min_top_k=settings.retrieval_top_k if model_backed else 0,
    )


@lru_cache
def get_query_service() -> QueryService:
    settings = get_settings()
    evidence = UploadedEvidenceRepository(
        settings.index_dir / "uploaded_evidence.json"
    ).load()
    return build_query_service(
        evidence,
        settings,
        uploads_dir=settings.uploads_dir,
        cache_dir=settings.index_dir,
    )


@lru_cache
def get_ingestion_service() -> DocumentIngestionService:
    settings = get_settings()
    return DocumentIngestionService(
        settings.uploads_dir,
        UploadedEvidenceRepository(settings.index_dir / "uploaded_evidence.json"),
        max_file_size_mb=settings.max_file_size_mb,
        redact=settings.redact_contact_details,
        ocr=settings.ocr_enabled,
    )
