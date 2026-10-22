from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import (
    hash_password,
    needs_rehash,
    new_token,
    token_digest,
    verify_password,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AuthSession, User, Workspace


def normalize_email(email: str) -> str:
    return email.strip().lower()


def check_password_policy(password: str, email: str) -> None:
    minimum = get_settings().min_password_length
    if len(password) < minimum:
        raise AppError(
            422, "weak_password", f"Use a password of at least {minimum} characters."
        )
    if len(password) > 200:
        raise AppError(
            422, "weak_password", "Use a password of at most 200 characters."
        )
    if password.strip().lower() == email:
        raise AppError(422, "weak_password", "Your password can't be your email.")


def sign_up(db: Session, *, email: str, password: str, name: str) -> User:
    email = normalize_email(email)
    check_password_policy(password, email)
    user = User(
        email=email,
        name=name.strip() or email.split("@")[0],
        password_hash=hash_password(password),
    )
    user.workspaces.append(Workspace(name="My workspace"))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            409, "email_taken", "An account with that email already exists."
        ) from exc
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if not verify_password(user.password_hash if user else None, password):
        raise AppError(
            401, "invalid_credentials", "That email and password don't match."
        )
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    return user


def start_session(
    db: Session, user: User, user_agent: str | None
) -> tuple[str, AuthSession]:
    """A new session for ``user``. Returns the raw token for the cookie."""
    token = new_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=token_digest(token),
        csrf_token=new_token(),
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().session_days),
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(session)
    db.flush()
    return token, session


def find_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_digest(token))
    )
    if session is None:
        return None
    if session.expires_at <= datetime.now(UTC):
        db.delete(session)
        db.commit()
        return None
    return session


def end_session(db: Session, session: AuthSession) -> None:
    db.execute(delete(AuthSession).where(AuthSession.id == session.id))


def workspace_for(db: Session, user: User) -> Workspace:
    workspace = db.scalar(
        select(Workspace)
        .where(Workspace.owner_id == user.id)
        .order_by(Workspace.created_at)
        .limit(1)
    )
    if workspace is None:  # pragma: no cover - every sign-up creates one
        workspace = Workspace(owner_id=user.id, name="My workspace")
        db.add(workspace)
        db.flush()
    return workspace
