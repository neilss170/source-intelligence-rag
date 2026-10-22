"""Queries for user data, always scoped to one workspace.

Route handlers reach user data only through these functions, and every one of
them takes a ``workspace_id`` and filters by it. An item that exists in
another workspace is reported exactly like one that does not exist.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.db.models import Chat, Message


def list_chats(db: Session, workspace_id: uuid.UUID) -> list[Chat]:
    return list(
        db.scalars(
            select(Chat)
            .where(Chat.workspace_id == workspace_id)
            .order_by(Chat.updated_at.desc(), Chat.created_at.desc())
        )
    )


def get_chat(db: Session, workspace_id: uuid.UUID, chat_id: uuid.UUID) -> Chat:
    chat = db.scalar(
        select(Chat).where(Chat.id == chat_id, Chat.workspace_id == workspace_id)
    )
    if chat is None:
        raise not_found("That chat")
    return chat


def create_chat(db: Session, workspace_id: uuid.UUID, title: str) -> Chat:
    chat = Chat(workspace_id=workspace_id, title=title.strip())
    db.add(chat)
    db.flush()
    db.refresh(chat)
    return chat


def rename_chat(
    db: Session, workspace_id: uuid.UUID, chat_id: uuid.UUID, title: str
) -> Chat:
    chat = get_chat(db, workspace_id, chat_id)
    chat.title = title.strip()
    chat.updated_at = datetime.now(UTC)
    db.flush()
    return chat


def delete_chat(db: Session, workspace_id: uuid.UUID, chat_id: uuid.UUID) -> None:
    db.delete(get_chat(db, workspace_id, chat_id))
    db.flush()


def list_messages(
    db: Session, workspace_id: uuid.UUID, chat_id: uuid.UUID
) -> list[Message]:
    get_chat(db, workspace_id, chat_id)
    return list(
        db.scalars(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at, Message.id)
        )
    )
