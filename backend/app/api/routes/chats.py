import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import Caller, current_caller
from app.chat.deps import get_chat_service
from app.chat.service import ChatService, Turn
from app.db import repository
from app.db.session import get_db
from app.models.account import ChatCreate, ChatOut, ChatUpdate, MessageOut

router = APIRouter(tags=["chats"])


@router.get("/chats", response_model=list[ChatOut])
def list_chats(
    caller: Caller = Depends(current_caller), db: Session = Depends(get_db)
) -> list[ChatOut]:
    return [
        ChatOut.model_validate(c)
        for c in repository.list_chats(db, caller.workspace.id)
    ]


@router.post("/chats", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
def create_chat(
    body: ChatCreate,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
) -> ChatOut:
    chat = repository.create_chat(db, caller.workspace.id, body.title)
    result = ChatOut.model_validate(chat)
    db.commit()
    return result


@router.patch("/chats/{chat_id}", response_model=ChatOut)
def rename_chat(
    chat_id: uuid.UUID,
    body: ChatUpdate,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
) -> ChatOut:
    chat = repository.rename_chat(db, caller.workspace.id, chat_id, body.title)
    result = ChatOut.model_validate(chat)
    db.commit()
    return result


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(
    chat_id: uuid.UUID,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
) -> Response:
    repository.delete_chat(db, caller.workspace.id, chat_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
def list_messages(
    chat_id: uuid.UUID,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    return [
        MessageOut.model_validate(m)
        for m in repository.list_messages(db, caller.workspace.id, chat_id)
    ]


class MessageCreate(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    scope: Literal["auto", "workspace", "general"] = "auto"


@router.post("/chats/{chat_id}/messages")
def send_message(
    chat_id: uuid.UUID,
    body: MessageCreate,
    caller: Caller = Depends(current_caller),
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """Ask a question; the answer streams back as server-sent events.

    Ownership is checked before streaming starts, so another user's chat is a
    plain 404 like everywhere else, not a stream that fails part-way.
    """
    repository.get_chat(db, caller.workspace.id, chat_id)
    turn = Turn(
        user_id=caller.user.id,
        workspace_id=caller.workspace.id,
        chat_id=chat_id,
        question=body.question.strip(),
        scope=body.scope,
    )
    return StreamingResponse(
        service.run(turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
