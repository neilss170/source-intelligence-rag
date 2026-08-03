from dataclasses import dataclass
from typing import Protocol

from app.models.resume import EvidenceUnit


class PairScorer(Protocol):
    def predict(self, pairs: list[tuple[str, str]]): ...


@dataclass(frozen=True, slots=True)
class RerankedEvidence:
    evidence: EvidenceUnit
    score: float


class CrossEncoderReranker:
    def __init__(
        self,
        retriever,
        *,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        candidate_k: int = 8,
        scorer: PairScorer | None = None,
    ) -> None:
        self._retriever = retriever
        self._candidate_k = candidate_k
        if scorer is None:
            from sentence_transformers import CrossEncoder

            scorer = CrossEncoder(model_name)
        self._scorer = scorer

    def search(self, query: str, *, top_k: int = 5) -> list[RerankedEvidence]:
        candidates = self._retriever.search(
            query,
            top_k=max(top_k, self._candidate_k),
        )
        if not candidates:
            return []
        pairs = [
            (
                query,
                " | ".join(
                    [
                        hit.evidence.title,
                        hit.evidence.organization or "",
                        hit.evidence.text,
                    ]
                ),
            )
            for hit in candidates
        ]
        scores = self._scorer.predict(pairs)
        reranked = sorted(
            (
                RerankedEvidence(evidence=hit.evidence, score=float(score))
                for hit, score in zip(candidates, scores, strict=True)
            ),
            key=lambda hit: (-hit.score, hit.evidence.evidence_id),
        )
        return reranked[:top_k]
