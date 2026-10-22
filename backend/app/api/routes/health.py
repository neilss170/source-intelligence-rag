import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.redis_client import get_redis
from app.db.session import get_engine
from app.models.health import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is up. Cheap, touches nothing else."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
    )


@router.get("/ready")
def ready() -> JSONResponse:
    """Readiness: everything a request needs is reachable."""
    checks: dict[str, str] = {}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report any failure as not ready
        logger.warning("Readiness: database unavailable: %s", exc)
        checks["database"] = "unavailable"
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Readiness: redis unavailable: %s", exc)
        checks["redis"] = "unavailable"
    ready_now = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ready" if ready_now else "not_ready", "checks": checks},
        status_code=200 if ready_now else 503,
    )
