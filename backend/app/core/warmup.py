"""Load the models before the first question needs them.

The embedder, reranker and claim checker take seconds to load - longer when
a fresh container downloads them - and the first question used to pay for
all three. They now load in a background thread at startup, and
``/api/ready`` reports not ready until they have, so a load balancer keeps
traffic away from an instance that would stall.
"""

import logging
import threading

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state = {"status": "not_started", "error": None}


def status() -> str:
    """``not_started``, ``loading``, ``ready`` or ``failed``."""
    return _state["status"]


def limit_cpu_threads() -> None:
    """Fewer PyTorch threads per call, so concurrent calls don't contend."""
    threads = get_settings().torch_threads
    if threads:
        import torch

        torch.set_num_threads(threads)


def start() -> None:
    limit_cpu_threads()
    with _lock:
        if _state["status"] != "not_started":
            return
        _state["status"] = "loading"
    threading.Thread(target=_load, name="model-warmup", daemon=True).start()


def _load() -> None:
    from app.chat.deps import get_chat_service
    from app.services.dense_retriever import load_encoder

    settings = get_settings()
    try:
        load_encoder(settings.dense_model)
        service = get_chat_service()
        # The lazy wrappers load on first attribute access.
        service._ranker.score  # noqa: B018
        if service._verifier is not None:
            service._verifier.verify  # noqa: B018
        _state["status"] = "ready"
        logger.info("Models loaded")
    except Exception as exc:  # noqa: BLE001 - reported through readiness
        logger.exception("Model warm-up failed")
        _state["status"], _state["error"] = "failed", str(exc)
