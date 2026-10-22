import threading
from functools import lru_cache

from app.chat.providers import ExhaustionStore, ModelRouter, model_chain
from app.chat.service import ChatService
from app.core.config import get_settings
from app.core.redis_client import get_redis
from app.db.session import get_sessionmaker
from app.services.citation_support import SupportVerifier
from app.services.cross_encoder_reranker import CrossEncoderReranker
from app.services.web_search import TavilySearchProvider


class _Lazy:
    """Builds the wrapped object on first use, once, even under concurrency.

    The reranker and claim checker are models that take seconds to load; a
    request refused before it needs them - signed out, someone else's chat -
    should not pay for that.
    """

    def __init__(self, build) -> None:
        self._build = build
        self._value = None
        self._lock = threading.Lock()

    def __getattr__(self, name):
        if self._value is None:
            with self._lock:
                if self._value is None:
                    self._value = self._build()
        return getattr(self._value, name)


@lru_cache
def get_chat_service() -> ChatService:
    """One service per process: models load once, quota state is shared."""
    settings = get_settings()
    chain = model_chain(settings)
    return ChatService(
        settings=settings,
        sessions=get_sessionmaker(),
        router=ModelRouter(chain, ExhaustionStore(get_redis())) if chain else None,
        ranker=_Lazy(
            lambda: CrossEncoderReranker(
                None, model_name=settings.reranker_model, probabilities=True
            )
        ),
        verifier=(
            _Lazy(
                lambda: SupportVerifier(
                    settings.nli_model, threshold=settings.support_threshold
                )
            )
            if settings.verify_citations
            else None
        ),
        web=TavilySearchProvider(
            settings.tavily_api_key if settings.web_search_enabled else None,
            country=settings.search_country,
            max_results=settings.search_max_results,
        ),
    )
