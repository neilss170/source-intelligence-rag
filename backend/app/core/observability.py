"""Logs and metrics.

**Logs** are one JSON object per line in production (``LOG_FORMAT=json``,
the default outside development), each carrying the request ID that is also
returned to the client, so one ID finds every line of a request. Fields
passed with ``extra={...}`` become top-level keys.

**Metrics** are served in Prometheus format at ``/metrics`` on the API port.
nginx only forwards ``/api/``, so they are not public.
"""

import json
import logging
import sys
import time
from datetime import UTC, datetime

from prometheus_client import Counter, Gauge, Histogram
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import request_id_var

# -- metrics -------------------------------------------------------------------

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests.", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Time to the response headers.",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
ANSWERS = Counter("answers_total", "Answers, by how they ended.", ["mode"])
ANSWER_STAGE = Histogram(
    "answer_stage_seconds",
    "Time per stage of answering.",
    ["stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32),
)
GROUNDEDNESS = Histogram(
    "answer_groundedness",
    "Share of cited sentences supported by their sources.",
    buckets=(0.0, 0.25, 0.5, 0.75, 0.9, 1.0),
)
TOKENS = Counter(
    "llm_tokens_total", "Tokens sent and received.", ["model", "direction"]
)
PROVIDER_ERRORS = Counter(
    "llm_provider_errors_total", "Failed provider calls.", ["model", "status"]
)
MODEL_EXHAUSTED = Counter(
    "llm_model_exhausted_total", "Times a model ran out of quota.", ["model"]
)
DOCUMENTS = Gauge("documents", "Documents by indexing status.", ["status"])
QUEUE_DEPTH = Gauge("ingestion_queue_depth", "Documents waiting for a worker.")


class MetricsMiddleware:
    """Counts requests and their latency, by route template (not raw path,
    which would make one series per document ID)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = {"code": 500}

        async def tracking_send(message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                route = scope.get("route")
                template = getattr(route, "path", "unmatched")
                elapsed = time.perf_counter() - started
                HTTP_LATENCY.labels(scope["method"], template).observe(elapsed)
                HTTP_REQUESTS.labels(scope["method"], template, status["code"]).inc()
                if template.startswith("/api/") and not template.startswith(
                    ("/api/health", "/api/ready")
                ):
                    logging.getLogger("app.access").info(
                        "%s %s %s",
                        scope["method"],
                        template,
                        status["code"],
                        extra={
                            "method": scope["method"],
                            "route": template,
                            "status": status["code"],
                            "ms": round(elapsed * 1000),
                        },
                    )
            await send(message)

        await self.app(scope, receive, tracking_send)


def refresh_gauges() -> None:
    """Read counts that live elsewhere (database, queue) at scrape time."""
    from sqlalchemy import func, select

    from app.core.redis_client import get_redis
    from app.db.models import Document
    from app.db.session import get_sessionmaker

    try:
        with get_sessionmaker()() as db:
            counts = dict(
                db.execute(
                    select(Document.status, func.count()).group_by(Document.status)
                ).all()
            )
        for status in ("uploaded", "indexing", "ready", "failed"):
            DOCUMENTS.labels(status).set(counts.get(status, 0))
    except Exception:  # noqa: BLE001 - a scrape must not fail on this
        logging.getLogger(__name__).warning("Could not count documents for metrics")
    try:
        QUEUE_DEPTH.set(get_redis().zcard("arq:queue"))
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("Could not read the queue for metrics")


# -- logs ----------------------------------------------------------------------

_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        entry.update(
            {
                k: v
                for k, v in vars(record).items()
                if k not in _STANDARD and k[0] != "_"
            }
        )
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Our access log replaces uvicorn's, which lacks request IDs and routes.
    logging.getLogger("uvicorn.access").disabled = True
