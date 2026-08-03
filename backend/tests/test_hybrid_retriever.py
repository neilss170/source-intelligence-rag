from dataclasses import dataclass
from pathlib import Path

from app.services.evidence_repository import EvidenceRepository
from app.services.hybrid_retriever import HybridRetriever

EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "reference_evidence.json"
)


@dataclass(frozen=True)
class Hit:
    evidence: object
    score: float


class FixedRetriever:
    def __init__(self, ordered_evidence: list) -> None:
        self._evidence = ordered_evidence

    def search(self, query: str, *, top_k: int = 5) -> list[Hit]:
        return [
            Hit(evidence=evidence, score=1.0) for evidence in self._evidence[:top_k]
        ]


def test_rrf_rewards_evidence_returned_by_both_retrievers() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    hybrid = HybridRetriever(
        FixedRetriever([evidence[0], evidence[1]]),
        FixedRetriever([evidence[1], evidence[2]]),
    )

    hits = hybrid.search("question")

    assert hits[0].evidence.evidence_id == evidence[1].evidence_id
