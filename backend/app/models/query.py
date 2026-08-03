from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.resume import EvidenceUnit, ResumeSection


class QueryType(StrEnum):
    FACTUAL = "factual"
    SKILL = "skill"
    SYNTHESIS = "synthesis"
    BEHAVIORAL = "behavioral"
    EVALUATIVE = "evaluative"
    OFF_TOPIC = "off_topic"


class QueryScope(StrEnum):
    AUTO = "auto"
    WORKSPACE = "workspace"
    GENERAL = "general"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1, max_length=4000)


class AnswerMode(StrEnum):
    WORKSPACE = "workspace"
    GENERAL = "general"
    EMPTY_WORKSPACE = "empty_workspace"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED_ANALYSIS = "unsupported_analysis"


class QueryRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_type: QueryType
    sections: list[ResumeSection] = Field(default_factory=list)
    date_from: int | None = Field(default=None, ge=1900, le=2100)
    date_to: int | None = Field(default=None, ge=1900, le=2100)
    entities: list[str] = Field(default_factory=list)
    requires_synthesis: bool = False

    @model_validator(mode="after")
    def validate_date_range(self) -> "QueryRoute":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be later than date_to")
        return self


class RetrievalHit(BaseModel):
    evidence: EvidenceUnit
    vector_score: float | None = Field(default=None, ge=0, le=1)
    keyword_score: float | None = Field(default=None, ge=0)
    fused_score: float = Field(ge=0)
    rank: int = Field(ge=1)


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    session_id: str | None = Field(default=None, max_length=100)
    top_k: int = Field(default=5, ge=1, le=20)
    scope: QueryScope = QueryScope.AUTO
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False

    @model_validator(mode="after")
    def validate_evidence_state(self) -> "GeneratedAnswer":
        if not self.insufficient_evidence and not self.evidence_ids:
            raise ValueError("a grounded answer must contain at least one evidence ID")
        return self


class GroundednessResult(BaseModel):
    grounded: bool
    score: float = Field(ge=0, le=1)
    unsupported_claims: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    evidence_id: str
    section: ResumeSection
    title: str
    filename: str
    page: int | None = Field(default=None, ge=1)
    excerpt: str
    relevance: float = Field(ge=0, le=1)


class WebSource(BaseModel):
    title: str
    url: str
    excerpt: str = ""


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    web_sources: list[WebSource] = Field(default_factory=list)
    grounded: bool
    groundedness_score: float = Field(ge=0, le=1)
    query_type: QueryType
    retrieval_ms: int = Field(ge=0)
    generation_ms: int = Field(ge=0)
    mode: AnswerMode = AnswerMode.WORKSPACE
