from dataclasses import dataclass

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.auth.security import tokens_match
from app.auth.service import find_session, workspace_for
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AuthSession, User, Workspace
from app.db.session import get_db

SESSION_COOKIE = "si_session"
#: Readable by the page, which echoes it in the X-CSRF-Token header.
CSRF_COOKIE = "si_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Caller:
    user: User
    workspace: Workspace
    session: AuthSession


def current_caller(request: Request, db: Session = Depends(get_db)) -> Caller:
    """The signed-in user and their workspace, or a 401.

    State-changing requests must also echo the session's CSRF token in a
    header. The session cookie is SameSite=Lax already; the header check
    covers browsers and proxies where that is not enough.
    """
    session = find_session(db, request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise AppError(401, "not_authenticated", "Sign in to continue.")
    if request.method not in _SAFE_METHODS and not tokens_match(
        session.csrf_token, request.headers.get(CSRF_HEADER)
    ):
        raise AppError(
            403, "csrf_failed", "This request could not be verified. Reload the page."
        )
    return Caller(
        user=session.user, workspace=workspace_for(db, session.user), session=session
    )


def set_session_cookies(response: Response, token: str, session: AuthSession) -> None:
    settings = get_settings()
    max_age = settings.session_days * 24 * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        session.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")
