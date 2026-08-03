from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.query import QueryType


class FeedbackValue(StrEnum):
    UP = "up"
    DOWN = "down"


class QueryEvent(BaseModel):
    event_id: str
    created_at: datetime
    anonymous_session_id: str
    question: str
    query_type: QueryType
    evidence_ids: list[str]
    retrieval_strategy: str
    retrieval_ms: int = Field(ge=0)
    generation_ms: int = Field(ge=0)
    groundedness_score: float = Field(ge=0, le=1)
    grounded: bool
    feedback: FeedbackValue | None = None
