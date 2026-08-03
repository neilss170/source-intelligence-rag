from app.models.query import AnswerMode, QueryScope
from app.services.tokenization import tokenize

WORKSPACE_TERMS = {
    "according",
    "csv",
    "data",
    "dataset",
    "document",
    "documents",
    "file",
    "files",
    "indexed",
    "pdf",
    "spreadsheet",
    "table",
    "uploaded",
}
ANALYSIS_TERMS = {
    "average",
    "calculate",
    "column",
    "correlation",
    "count",
    "maximum",
    "mean",
    "median",
    "minimum",
    "rows",
    "sum",
    "trend",
}
AMBIGUOUS_SINGLE_TERMS = {
    "college",
    "data",
    "document",
    "help",
    "project",
    "school",
    "summary",
}


def route_answer_mode(
    question: str,
    scope: QueryScope,
    *,
    has_documents: bool,
    has_structured_data: bool = False,
) -> AnswerMode:
    terms = set(tokenize(question))
    if scope is QueryScope.GENERAL:
        return AnswerMode.GENERAL
    if scope is QueryScope.WORKSPACE:
        return AnswerMode.WORKSPACE if has_documents else AnswerMode.EMPTY_WORKSPACE
    if len(terms) == 1 and terms & AMBIGUOUS_SINGLE_TERMS:
        return AnswerMode.AMBIGUOUS
    if terms & ANALYSIS_TERMS and has_documents and not has_structured_data:
        return AnswerMode.UNSUPPORTED_ANALYSIS
    if has_documents:
        return AnswerMode.WORKSPACE
    if terms & WORKSPACE_TERMS:
        return AnswerMode.EMPTY_WORKSPACE
    return AnswerMode.GENERAL
