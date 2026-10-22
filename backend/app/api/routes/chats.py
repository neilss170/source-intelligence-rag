import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import Caller, current_caller
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
