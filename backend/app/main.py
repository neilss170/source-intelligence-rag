from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.auth.deps import CSRF_HEADER
from app.core import warmup
from app.core.config import get_settings
from app.core.errors import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    install_error_handlers,
)
from app.core.limits import BodySizeLimit
from app.core.storage import ensure_storage_directories


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_storage_directories()
    if get_settings().warm_models:
        warmup.start()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="API for document-grounded question answering.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", CSRF_HEADER, REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        BodySizeLimit,
        path_prefix="/api/documents",
        # Every file at its limit, plus room for the multipart framing.
        max_bytes=settings.max_upload_files * settings.max_file_size_mb * 1024 * 1024
        + 1024 * 1024,
    )
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
