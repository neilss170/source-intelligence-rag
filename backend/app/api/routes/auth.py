from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import (
    Caller,
    clear_session_cookies,
    current_caller,
    set_session_cookies,
)
from app.auth.service import (
    authenticate,
    end_session,
    sign_up,
    start_session,
    workspace_for,
)
from app.db.models import AuthSession, User
from app.db.session import get_db
from app.models.account import (
    LogInRequest,
    SessionOut,
    SignUpRequest,
    UserOut,
    WorkspaceOut,
)

router = APIRouter(tags=["auth"])


def _session_out(db: Session, user: User, session: AuthSession) -> SessionOut:
    return SessionOut(
        user=UserOut.model_validate(user),
        workspace=WorkspaceOut.model_validate(workspace_for(db, user)),
        csrf_token=session.csrf_token,
    )


@router.post(
    "/auth/signup", response_model=SessionOut, status_code=status.HTTP_201_CREATED
)
def signup(
    body: SignUpRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> SessionOut:
    user = sign_up(db, email=body.email, password=body.password, name=body.name)
    token, session = start_session(db, user, request.headers.get("user-agent"))
    result = _session_out(db, user, session)
    db.commit()
    set_session_cookies(response, token, session)
    return result


@router.post("/auth/login", response_model=SessionOut)
def login(
    body: LogInRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> SessionOut:
    user = authenticate(db, email=body.email, password=body.password)
    token, session = start_session(db, user, request.headers.get("user-agent"))
    result = _session_out(db, user, session)
    db.commit()
    set_session_cookies(response, token, session)
    return result


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
) -> Response:
    end_session(db, caller.session)
    db.commit()
    clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=SessionOut)
def me(caller: Caller = Depends(current_caller)) -> SessionOut:
    return SessionOut(
        user=UserOut.model_validate(caller.user),
        workspace=WorkspaceOut.model_validate(caller.workspace),
        csrf_token=caller.session.csrf_token,
    )
