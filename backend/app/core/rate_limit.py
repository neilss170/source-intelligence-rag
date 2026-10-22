"""Fixed-window rate limits in Redis.

Each limit counts hits per key (a user, an IP address, an email) in the
current window and refuses with 429 and ``Retry-After`` once over. If Redis
is unreachable the request is let through and the failure logged: an outage
of the limiter must not become an outage of the product.
"""

import hashlib
import logging
import time
from dataclasses import dataclass

from fastapi import Depends, Request

from app.auth.deps import Caller, current_caller
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limit:
    name: str
    hits: int
    window_s: int
    message: str


_settings = get_settings()
QUESTIONS = Limit(
    "questions",
    _settings.rate_limit_questions_per_minute,
    60,
    "You're asking very quickly. Wait a moment.",
)
UPLOADS = Limit(
    "uploads",
    _settings.rate_limit_uploads_per_hour,
    3600,
    "You've uploaded a lot this hour. Try again later.",
)
AUTH = Limit(
    "auth",
    _settings.rate_limit_auth_per_15_minutes,
    15 * 60,
    "Too many sign-in attempts. Wait a few minutes and try again.",
)


def hit(limit: Limit, key: str) -> None:
    """Count one hit for ``key``; raise a 429 when the limit is exceeded."""
    window = int(time.time()) // limit.window_s
    redis_key = f"rl:{limit.name}:{key}:{window}"
    try:
        client = get_redis()
        pipeline = client.pipeline()
        pipeline.incr(redis_key)
        pipeline.expire(redis_key, limit.window_s + 5)
        count = pipeline.execute()[0]
    except Exception:  # noqa: BLE001 - fail open
        logger.warning("Rate limiter unavailable; allowing %s", limit.name)
        return
    if count > limit.hits:
        retry_after = limit.window_s - int(time.time()) % limit.window_s
        raise AppError(
            429, "rate_limited", limit.message, {"Retry-After": str(retry_after)}
        )


def client_ip(request: Request) -> str:
    # Behind nginx, uvicorn's --proxy-headers puts the real client here.
    return request.client.host if request.client else "unknown"


def _hashed(value: str) -> str:
    # Keys in Redis never hold raw emails.
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:24]


def limit_questions(caller: Caller = Depends(current_caller)) -> Caller:
    hit(QUESTIONS, str(caller.user.id))
    return caller


def limit_uploads(caller: Caller = Depends(current_caller)) -> Caller:
    hit(UPLOADS, str(caller.user.id))
    return caller


def limit_auth(request: Request, email: str) -> None:
    """Sign-in and sign-up attempts, per address and per account."""
    hit(AUTH, f"ip:{client_ip(request)}")
    hit(AUTH, f"email:{_hashed(email)}")
