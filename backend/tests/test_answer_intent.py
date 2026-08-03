import pytest

from app.services.answer_intent import AnswerIntent, detect_answer_intent


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Did they use Python?", AnswerIntent.YES_NO),
        ("Where did they study?", AnswerIntent.WHERE),
        ("When did they graduate?", AnswerIntent.WHEN),
        ("Who developed the project?", AnswerIntent.WHO),
        ("Which programming languages are listed?", AnswerIntent.LIST),
        ("Summarize this document", AnswerIntent.SUMMARY),
        ("How does the system work?", AnswerIntent.EXPLANATION),
        ("What is their degree?", AnswerIntent.LIST),
    ],
)
def test_detects_expected_answer_shape(question: str, expected: AnswerIntent) -> None:
    assert detect_answer_intent(question) is expected
