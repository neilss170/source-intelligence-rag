from app.models.query import ChatMessage, ChatRole, QueryRequest, QueryScope
from app.models.resume import EvidenceUnit, ResumeSection, SourceReference
from app.services.grounded_generator import GroundedGenerator
from app.services.query_service import QueryService


class RecordingGeneralProvider:
    def __init__(self) -> None:
        self.history = []

    def answer(self, question, history):
        self.history = history
        return "It refers to retrieval-augmented generation."


def test_general_chat_receives_recent_conversation_history() -> None:
    provider = RecordingGeneralProvider()
    service = QueryService(None, GroundedGenerator(), provider)
    history = [
        ChatMessage(role=ChatRole.USER, content="What does RAG mean?"),
        ChatMessage(
            role=ChatRole.ASSISTANT,
            content="RAG means retrieval-augmented generation.",
        ),
    ]

    response = service.query(
        QueryRequest(
            question="How does it work?",
            scope=QueryScope.GENERAL,
            history=history,
        )
    )

    assert response.answer.startswith("It refers")
    assert provider.history == history


class UnrelatedRetriever:
    def search(self, query, *, top_k=5):
        evidence = EvidenceUnit(
            evidence_id="ev_document_resume_999",
            section=ResumeSection.DOCUMENT,
            title="Resume",
            text="Neil developed machine-learning projects using Python.",
            source=SourceReference(
                document_id="doc_resume",
                filename="resume.pdf",
                page=1,
                source_text="Resume source",
            ),
        )
        return [type("Hit", (), {"evidence": evidence, "score": 0.4})()]


def test_auto_mode_routes_unrelated_question_away_from_documents() -> None:
    provider = RecordingGeneralProvider()
    response = QueryService(
        UnrelatedRetriever(),
        GroundedGenerator(),
        provider,
    ).query(
        QueryRequest(
            question="Can you name a few mechanical keyboards?",
            scope=QueryScope.AUTO,
        )
    )

    assert response.mode.value == "general"
    assert response.citations == []
    assert response.grounded is False
