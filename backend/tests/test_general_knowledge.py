from app.services.general_knowledge import (
    _asks_for_links,
    _first_sentences,
    _looks_factual,
    _safe_link_response,
)


def test_detects_factual_general_question() -> None:
    assert _looks_factual("What is retrieval-augmented generation?") is True
    assert _looks_factual("Who developed Python?") is True


def test_does_not_force_conversational_request_into_factual_lookup() -> None:
    assert _looks_factual("Write a friendly welcome message") is False


def test_trims_external_summary_without_cutting_sentence() -> None:
    text = "First fact. Second fact. Third fact. Fourth fact."

    assert _first_sentences(text, limit=3) == ("First fact. Second fact. Third fact.")


def test_link_request_is_detected_and_does_not_invent_urls() -> None:
    question = "Can you name mechanical keyboards and provide links?"

    assert _asks_for_links(question) is True
    answer = _safe_link_response(question)
    assert "Keychron" in answer
    assert "won't invent URLs" in answer
    assert "http" not in answer
