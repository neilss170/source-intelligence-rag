import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.models.resume import EvidenceUnit


class PairScorer(Protocol):
    def predict(self, pairs: list[tuple[str, str]]): ...


@dataclass(frozen=True, slots=True)
class RerankedEvidence:
    evidence: EvidenceUnit
    score: float


@lru_cache
def load_cross_encoder(model_name: str):
    """One reranker per process: uploads rebuild the retriever, not the model."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


class CrossEncoderReranker:
    def __init__(
        self,
        retriever,
        *,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        candidate_k: int = 8,
        scorer: PairScorer | None = None,
        probabilities: bool = False,
        min_score: float | None = None,
        min_keep: int = 0,
    ) -> None:
        """Rerank another retriever's candidates.

        Args:
            probabilities: Report ``sigmoid(logit)`` instead of the raw logit,
                so scores read as 0-1 relevance and a threshold means something.
            min_score: Drop passages scoring below this, after ``min_keep``.
            min_keep: Passages always kept, best first, whatever their score -
                the model judges what is irrelevant; an empty context cannot.
        """
        self._retriever = retriever
        self._candidate_k = candidate_k
        self._scorer = scorer or load_cross_encoder(model_name)
        self._probabilities = probabilities
        self._min_score = min_score
        self._min_keep = min_keep

    def score(self, query: str, evidence: list[EvidenceUnit]) -> list[float]:
        """Relevance of each passage to ``query``, in the given order."""
        if not evidence:
            return []
        pairs = [
            (
                query,
                " | ".join([item.title, item.organization or "", item.text]),
            )
            for item in evidence
        ]
        scores = [float(score) for score in self._scorer.predict(pairs)]
        if self._probabilities:
            scores = [1 / (1 + math.exp(-score)) for score in scores]
        return scores

    def search(self, query: str, *, top_k: int = 5) -> list[RerankedEvidence]:
        candidates = self._retriever.search(
            query,
            top_k=max(top_k, self._candidate_k),
        )
        if not candidates:
            return []
        scores = self.score(query, [hit.evidence for hit in candidates])
        reranked = sorted(
            (
                RerankedEvidence(evidence=hit.evidence, score=score)
                for hit, score in zip(candidates, scores, strict=True)
            ),
            key=lambda hit: (-hit.score, hit.evidence.evidence_id),
        )[:top_k]
        if self._min_score is None:
            return reranked
        return [
            hit
            for index, hit in enumerate(reranked)
            if index < self._min_keep or hit.score >= self._min_score
        ]
