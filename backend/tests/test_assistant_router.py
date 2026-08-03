from app.models.query import AnswerMode, QueryScope
from app.services.assistant_router import route_answer_mode


def test_empty_workspace_routes_document_question_to_upload_guidance() -> None:
    assert (
        route_answer_mode(
            "Summarize the uploaded document",
            QueryScope.AUTO,
            has_documents=False,
        )
        is AnswerMode.EMPTY_WORKSPACE
    )


def test_empty_workspace_routes_general_question_to_general_model() -> None:
    assert (
        route_answer_mode(
            "Why is the sky blue?",
            QueryScope.AUTO,
            has_documents=False,
        )
        is AnswerMode.GENERAL
    )


def test_explicit_general_scope_bypasses_documents() -> None:
    assert (
        route_answer_mode(
            "Explain machine learning",
            QueryScope.GENERAL,
            has_documents=True,
        )
        is AnswerMode.GENERAL
    )


def test_explicit_workspace_scope_requires_documents() -> None:
    assert (
        route_answer_mode(
            "What is the refund period?",
            QueryScope.WORKSPACE,
            has_documents=False,
        )
        is AnswerMode.EMPTY_WORKSPACE
    )


def test_short_ambiguous_question_requests_clarification() -> None:
    assert (
        route_answer_mode(
            "summary?",
            QueryScope.AUTO,
            has_documents=False,
        )
        is AnswerMode.AMBIGUOUS
    )
