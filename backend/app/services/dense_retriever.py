from dataclasses import dataclass

import numpy as np
from sentence_transformers import SentenceTransformer

from app.models.resume import EvidenceUnit, ResumeSection


@dataclass(frozen=True, slots=True)
class DenseScoredEvidence:
    evidence: EvidenceUnit
    score: float


class DenseRetriever:
    def __init__(
        self,
        evidence: list[EvidenceUnit],
        *,
        model_name: str = "BAAI/bge-small-en-v1.5",
        minimum_score: float = 0.35,
    ) -> None:
        if not evidence:
            raise ValueError("Dense retrieval requires at least one evidence unit")
        self._evidence = evidence
        self._minimum_score = minimum_score
        self._model = SentenceTransformer(model_name)
        documents = [
            " | ".join(
                [
                    item.section.value,
                    item.title,
                    item.organization or "",
                    ", ".join(item.technologies),
                    item.text,
                ]
            )
            for item in evidence
        ]
        self._embeddings = np.asarray(
            self._model.encode(documents, normalize_embeddings=True),
            dtype=np.float32,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        sections: set[ResumeSection] | None = None,
    ) -> list[DenseScoredEvidence]:
        if not query.strip():
            return []
        query_embedding = np.asarray(
            self._model.encode(
                [query],
                prompt_name="query",
                normalize_embeddings=True,
            ),
            dtype=np.float32,
        )[0]
        scores = self._embeddings @ query_embedding
        ranked_indices = np.argsort(-scores)
        return [
            DenseScoredEvidence(
                evidence=self._evidence[int(index)],
                score=float(scores[index]),
            )
            for index in ranked_indices
            if scores[index] >= self._minimum_score
            and (sections is None or self._evidence[int(index)].section in sections)
        ][:top_k]
