from functools import lru_cache

from app.core.config import get_settings
from app.services.adaptive_retriever import AdaptiveTopKRetriever
from app.services.cross_encoder_reranker import CrossEncoderReranker
from app.services.dense_retriever import DenseRetriever
from app.services.document_ingestion import DocumentIngestionService
from app.services.entity_guard import EntityGuardRetriever
from app.services.general_knowledge import LocalGeneralKnowledgeProvider
from app.services.grounded_generator import GroundedGenerator
from app.services.query_service import QueryService
from app.services.routed_retriever import RoutedDenseRetriever
from app.services.uploaded_evidence_repository import UploadedEvidenceRepository
from app.services.web_search import TavilySearchProvider


@lru_cache
def get_query_service() -> QueryService:
    uploaded_evidence = UploadedEvidenceRepository(
        get_settings().index_dir / "uploaded_evidence.json"
    ).load()
    retriever = None
    if uploaded_evidence:
        base_retriever = EntityGuardRetriever(
            RoutedDenseRetriever(DenseRetriever(uploaded_evidence, minimum_score=0.35)),
            uploaded_evidence,
        )
    settings = get_settings()
    if uploaded_evidence:
        if settings.reranker_enabled:
            base_retriever = CrossEncoderReranker(
                base_retriever,
                model_name=settings.reranker_model,
            )
        retriever = AdaptiveTopKRetriever(base_retriever)
    return QueryService(
        retriever,
        GroundedGenerator(),
        LocalGeneralKnowledgeProvider(
            api_key=settings.chat_api_key,
            api_base_url=settings.chat_api_base_url,
            chat_model=settings.chat_model,
            local_model=settings.local_chat_model,
        ),
        TavilySearchProvider(
            settings.tavily_api_key if settings.web_search_enabled else None,
            country=settings.search_country,
            max_results=settings.search_max_results,
        ),
    )


@lru_cache
def get_ingestion_service() -> DocumentIngestionService:
    settings = get_settings()
    return DocumentIngestionService(
        settings.uploads_dir,
        UploadedEvidenceRepository(settings.index_dir / "uploaded_evidence.json"),
        max_file_size_mb=settings.max_file_size_mb,
    )
