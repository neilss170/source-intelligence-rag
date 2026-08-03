from app.models.query import QueryType
from app.services.tokenization import tokenize


def classify_query(question: str) -> QueryType:
    terms = set(tokenize(question))
    if terms & {"hire", "suitable", "qualified", "fit"}:
        return QueryType.EVALUATIVE
    if terms & {"challenge", "example", "time"}:
        return QueryType.BEHAVIORAL
    if terms & {"describe", "strongest", "summarize"} or (
        "how" in terms and "project" in terms
    ):
        return QueryType.SYNTHESIS
    if terms & {
        "algorithm",
        "algorithms",
        "fastapi",
        "language",
        "languages",
        "react",
        "skill",
        "skills",
        "technologies",
    }:
        return QueryType.SKILL
    return QueryType.FACTUAL
