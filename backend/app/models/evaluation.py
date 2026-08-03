from pydantic import BaseModel, Field

from app.models.query import QueryType


class EvaluationCase(BaseModel):
    id: str = Field(pattern=r"^q\d{2}$")
    question: str = Field(min_length=2)
    query_type: QueryType
    relevant_evidence_ids: list[str]
    reference_answer: str = Field(min_length=1)
