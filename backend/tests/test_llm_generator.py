from app.models.query import ChatMessage, ChatRole, QueryRequest, QueryScope, QueryType
from app.models.resume import EvidenceUnit, ResumeSection, SourceReference
from app.services.bm25_retriever import ScoredEvidence
from app.services.llm_client import LLMError
from app.services.llm_generator import LLMGroundedGenerator, resolve_citations
from app.services.query_service import QueryService


class FakeClient:
    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.prompts = []
        self.model = "test-model"

    def complete_text(self, *, system, user, max_tokens=3000):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _hit(suffix: str, text: str, score: float = 0.8) -> ScoredEvidence:
    return ScoredEvidence(
        evidence=EvidenceUnit(
            evidence_id=f"ev_doc_{suffix}",
            section=ResumeSection.DOCUMENT,
            title=f"Section {suffix}",
            text=text,
            source=SourceReference(
                document_id="doc_report",
                filename="report.pdf",
                page=2,
                source_text=text,
            ),
        ),
        score=score,
    )


HITS = [
    _hit("a", "The 2024 budget for cloud hosting was 40,000 USD."),
    _hit("b", "Hosting moved from AWS to Azure in March."),
]


def test_resolve_citations_numbers_by_first_appearance_and_drops_unknown_ids() -> None:
    ids = {"E1": "ev_a", "E2": "ev_b"}
    answer, cited = resolve_citations(
        "Moved to Azure [E2]. Budget was 40k [E1, E2] [E9]. Again [E2-E1].", ids
    )
    assert answer == "Moved to Azure[1]. Budget was 40k[2][1]. Again."
    assert cited == ["ev_b", "ev_a"]


def test_model_answer_is_returned_with_cited_evidence() -> None:
    client = FakeClient("They spent 40,000 USD on hosting [E1], now on Azure [E2].")
    generated = LLMGroundedGenerator(client).generate(
        "How much do we spend on servers?", HITS, QueryType.FACTUAL
    )

    assert generated.answer == "They spent 40,000 USD on hosting[1], now on Azure[2]."
    assert generated.evidence_ids == ["ev_doc_a", "ev_doc_b"]
    assert "[E1] report.pdf, page 2 - Section a" in client.prompts[0]


def test_uncited_answer_counts_as_insufficient_evidence() -> None:
    client = FakeClient("The documents do not cover staffing.")
    generated = LLMGroundedGenerator(client).generate(
        "How many engineers are there?", HITS, QueryType.FACTUAL
    )

    assert generated.insufficient_evidence
    assert generated.evidence_ids == []


def test_provider_failure_falls_back_to_rule_based_answer() -> None:
    client = FakeClient(LLMError("rate limited"))
    generated = LLMGroundedGenerator(client).generate(
        "When did hosting move to Azure?", HITS, QueryType.FACTUAL
    )

    assert generated.answer
    assert not generated.answer.startswith("They spent")


def test_follow_up_is_rewritten_before_retrieval_and_history_is_replayed() -> None:
    searched = []

    class Retriever:
        def search(self, query, *, top_k=5):
            searched.append(query)
            return HITS

    client = FakeClient(
        "When did cloud hosting move to Azure?",
        "It moved in March [E2].",
    )
    history = [
        ChatMessage(role=ChatRole.USER, content="What is the hosting budget?"),
        ChatMessage(role=ChatRole.ASSISTANT, content="40,000 USD [1]."),
    ]
    response = QueryService(Retriever(), LLMGroundedGenerator(client)).query(
        QueryRequest(
            question="When did that move?",
            scope=QueryScope.WORKSPACE,
            history=history,
        )
    )

    assert searched == ["When did cloud hosting move to Azure?"]
    assert "Assistant: 40,000 USD ." in client.prompts[1]
    assert response.grounded
    assert response.answer == "It moved in March[1]."
    assert [c.evidence_id for c in response.citations] == ["ev_doc_b"]


class RecordingRetriever:
    def __init__(self) -> None:
        self.searched = []

    def search(self, query, *, top_k=5):
        self.searched.append(query)
        return HITS[:1]


def test_small_workspace_is_sent_whole_without_searching() -> None:
    retriever = RecordingRetriever()
    client = FakeClient("Budget was 40,000 USD [E1] and hosting moved [E2].")
    generator = LLMGroundedGenerator(client, workspace=[h.evidence for h in HITS])

    response = QueryService(retriever, generator).query(
        QueryRequest(question="Summarise my documents", scope=QueryScope.AUTO)
    )

    assert retriever.searched == []
    assert "(These are all of the uploaded passages.)" in client.prompts[0]
    assert "1 uploaded file(s):\n- report.pdf (2 passages, page 2)" in client.prompts[0]
    assert len(response.citations) == 2


def test_large_workspace_falls_back_to_search() -> None:
    retriever = RecordingRetriever()
    client = FakeClient("Budget was 40,000 USD [E1].")
    generator = LLMGroundedGenerator(
        client, workspace=[h.evidence for h in HITS], budget=10
    )

    QueryService(retriever, generator).query(
        QueryRequest(question="What is the budget?", scope=QueryScope.AUTO)
    )

    assert retriever.searched == ["What is the budget?"]
    assert "Only the passages a search found" in client.prompts[0]


def test_question_about_the_assistant_is_answered_by_the_model_directly() -> None:
    class FailingGeneral:
        def answer(self, question, history):
            raise AssertionError("general provider should not be called")

    client = FakeClient("You have one file uploaded, report.pdf.")
    generator = LLMGroundedGenerator(client, workspace=[h.evidence for h in HITS])

    response = QueryService(RecordingRetriever(), generator, FailingGeneral()).query(
        QueryRequest(question="What files have I uploaded?", scope=QueryScope.AUTO)
    )

    assert response.answer == "You have one file uploaded, report.pdf."
    assert response.mode.value == "general"
    assert response.grounded is False


def test_single_word_question_is_not_refused_when_the_model_answers() -> None:
    client = FakeClient("Here is a summary [E1].")
    generator = LLMGroundedGenerator(client, workspace=[h.evidence for h in HITS])

    response = QueryService(RecordingRetriever(), generator).query(
        QueryRequest(question="summary", scope=QueryScope.AUTO)
    )

    assert response.mode.value == "workspace"
    assert response.grounded


def test_no_history_skips_the_rewrite_call() -> None:
    client = FakeClient()
    generator = LLMGroundedGenerator(client)

    assert generator.rewrite_question("What is RAG?", []) == "What is RAG?"
    assert client.prompts == []
