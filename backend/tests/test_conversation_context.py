from app.models.query import ChatMessage, ChatRole
from app.services.conversation_context import resolve_follow_up


def test_short_follow_up_inherits_previous_user_topic() -> None:
    history = [
        ChatMessage(role=ChatRole.USER, content="Tell me about mechanical keyboards"),
        ChatMessage(
            role=ChatRole.ASSISTANT,
            content="Mechanical keyboards use individual switches.",
        ),
    ]

    resolved = resolve_follow_up("Name a few", history)

    assert "mechanical keyboards" in resolved
    assert resolved.endswith("Follow-up: Name a few")


def test_complete_question_is_not_rewritten() -> None:
    history = [ChatMessage(role=ChatRole.USER, content="Tell me about keyboards")]

    assert resolve_follow_up("Who founded Microsoft?", history) == (
        "Who founded Microsoft?"
    )


def test_follow_up_without_history_remains_unchanged() -> None:
    assert resolve_follow_up("Name a few", []) == "Name a few"
