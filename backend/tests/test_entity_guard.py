from dataclasses import dataclass
from pathlib import Path

from app.services.entity_guard import EntityGuardRetriever
from app.services.evidence_repository import EvidenceRepository

EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "reference_evidence.json"
)


@dataclass
class StubRetriever:
    called: bool = False

    def search(self, query: str, *, top_k: int = 5) -> list:
        self.called = True
        return ["result"]


def test_absent_explicit_entity_skips_semantic_retrieval() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    stub = StubRetriever()

    assert EntityGuardRetriever(stub, evidence).search("Does Neil know FastAPI?") == []
    assert stub.called is False


def test_present_explicit_entity_continues_to_retrieval() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    stub = StubRetriever()

    assert EntityGuardRetriever(stub, evidence).search(
        "Has Neil worked with Flask?"
    ) == ["result"]
    assert stub.called is True


def test_open_question_is_not_treated_as_absent_entity_lookup() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    stub = StubRetriever()

    assert EntityGuardRetriever(stub, evidence).search(
        "What machine learning algorithms does Neil list?"
    ) == ["result"]
    assert stub.called is True


def test_missing_sensitive_fact_does_not_force_semantic_match() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    stub = StubRetriever()

    assert EntityGuardRetriever(stub, evidence).search("What is Neil's salary?") == []
    assert stub.called is False
