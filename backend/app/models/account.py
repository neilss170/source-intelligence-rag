import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=120)


class LogInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class SessionOut(BaseModel):
    user: UserOut
    workspace: WorkspaceOut
    #: Send back in the X-CSRF-Token header on POST, PATCH and DELETE.
    csrf_token: str


class ChatCreate(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=200)


class ChatUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    citations: list
    unsupported_claims: list
    mode: str | None
    model: str | None
    groundedness: float | None
    created_at: datetime
