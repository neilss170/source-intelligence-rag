from enum import StrEnum

from pydantic import BaseModel, Field


class DocumentStatus(StrEnum):
    READY = "ready"
    DUPLICATE = "duplicate"


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    evidence_count: int = Field(ge=0)
