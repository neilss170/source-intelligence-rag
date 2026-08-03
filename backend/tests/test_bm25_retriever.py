from pathlib import Path

from app.services.bm25_retriever import BM25Retriever
from app.services.evidence_repository import EvidenceRepository

EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "reference_evidence.json"
)


def test_exact_skill_query_retrieves_skill_evidence_first() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    hits = BM25Retriever(evidence).search(
        "Which programming languages are listed?", top_k=3
    )

    assert hits[0].evidence.evidence_id == "ev_skills_programming_001"


def test_unknown_terms_return_no_results() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()

    assert BM25Retriever(evidence).search("kubernetes terraform golang") == []


def test_results_are_deterministic() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    retriever = BM25Retriever(evidence)

    assert retriever.search("diabetes prediction") == retriever.search(
        "diabetes prediction"
    )
