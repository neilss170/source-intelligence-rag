"""One error shape for the whole API, and a request ID on every response.

Every error is JSON with a stable machine-readable ``code``, a ``message`` a
person can read, and the ``request_id`` that also appears in the logs::

    {"detail": "...", "error": {"code": "not_found", "message": "...",
                                "request_id": "..."}}

``detail`` repeats the message for clients written against FastAPI's default
error shape.
"""

import logging
import uuid
from contextvars import ContextVar
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class AppError(Exception):
    """An expected failure with a stable code the client can act on."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found(what: str = "That item") -> AppError:
    # Also used for items owned by someone else: "not yours" and "does not
    # exist" must look identical, or IDs can be probed.
    return AppError(404, "not_found", f"{what} was not found.")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = (
            incoming
            if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum()
            else uuid.uuid4().hex
        )
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _error(request: Request, status: int, code: str, message: str, **extra):
    request_id = getattr(request.state, "request_id", request_id_var.get())
    body = {
        "detail": message,
        "error": {"code": code, "message": message, "request_id": request_id, **extra},
    }
    return JSONResponse(
        body, status_code=status, headers={REQUEST_ID_HEADER: request_id}
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return _error(request, exc.status, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = (
            exc.detail
            if isinstance(exc.detail, str)
            else HTTPStatus(exc.status_code).phrase
        )
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        response = _error(request, exc.status_code, code, message)
        for name, value in (exc.headers or {}).items():
            response.headers[name] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [
            {
                "field": ".".join(str(part) for part in error["loc"][1:]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        message = (
            f"{fields[0]['field'] or 'Request'}: {fields[0]['message']}"
            if fields
            else "The request is not valid."
        )
        return _error(request, 422, "invalid_request", message, fields=fields)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(
            request,
            500,
            "internal_error",
            "Something went wrong on our side. Try again in a moment.",
        )
