from dataclasses import dataclass

from app.models.resume import EvidenceUnit
from app.services.bm25_retriever import BM25Retriever
from app.services.dense_retriever import DenseRetriever


@dataclass(frozen=True, slots=True)
class HybridScoredEvidence:
    evidence: EvidenceUnit
    score: float


class HybridRetriever:
    def __init__(
        self,
        bm25: BM25Retriever,
        dense: DenseRetriever,
        *,
        rank_constant: int = 60,
        candidate_k: int = 10,
    ) -> None:
        self._bm25 = bm25
        self._dense = dense
        self._rank_constant = rank_constant
        self._candidate_k = candidate_k

    def search(self, query: str, *, top_k: int = 5) -> list[HybridScoredEvidence]:
        rankings = [
            self._bm25.search(query, top_k=self._candidate_k),
            self._dense.search(query, top_k=self._candidate_k),
        ]
        fused_scores: dict[str, float] = {}
        evidence_by_id: dict[str, EvidenceUnit] = {}
        for ranking in rankings:
            for rank, hit in enumerate(ranking, start=1):
                evidence_id = hit.evidence.evidence_id
                evidence_by_id[evidence_id] = hit.evidence
                fused_scores[evidence_id] = fused_scores.get(evidence_id, 0.0) + (
                    1 / (self._rank_constant + rank)
                )
        ordered = sorted(
            fused_scores,
            key=lambda evidence_id: (-fused_scores[evidence_id], evidence_id),
        )
        return [
            HybridScoredEvidence(
                evidence=evidence_by_id[evidence_id],
                score=fused_scores[evidence_id],
            )
            for evidence_id in ordered[:top_k]
        ]
