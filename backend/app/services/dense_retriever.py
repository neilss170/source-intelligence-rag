from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha1
from pathlib import Path

import numpy as np

from app.models.resume import EvidenceUnit, ResumeSection


@dataclass(frozen=True, slots=True)
class DenseScoredEvidence:
    evidence: EvidenceUnit
    score: float


@lru_cache
def load_encoder(model_name: str):
    """One encoder per process: uploads rebuild the retriever, not the model."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


class DenseRetriever:
    def __init__(
        self,
        evidence: list[EvidenceUnit],
        *,
        model_name: str = "BAAI/bge-small-en-v1.5",
        minimum_score: float = 0.35,
        cache_path: Path | None = None,
    ) -> None:
        if not evidence:
            raise ValueError("Dense retrieval requires at least one evidence unit")
        self._evidence = evidence
        self._minimum_score = minimum_score
        self._model = load_encoder(model_name)
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
        self._embeddings = self._embed(documents, model_name, cache_path)

    def _embed(
        self, documents: list[str], model_name: str, cache_path: Path | None
    ) -> np.ndarray:
        """Embeddings for ``documents``, reusing any computed before.

        Keyed by a hash of the model and the exact text, so a re-chunked or
        edited passage is re-embedded and an unchanged one never is.
        """
        keys = [sha1(f"{model_name}\n{doc}".encode()).hexdigest() for doc in documents]
        cached: dict[str, np.ndarray] = {}
        if cache_path and cache_path.exists():
            with np.load(cache_path) as stored:
                cached = dict(
                    zip(stored["keys"].tolist(), stored["vectors"], strict=True)
                )
        missing = [i for i, key in enumerate(keys) if key not in cached]
        if missing:
            vectors = np.asarray(
                self._model.encode(
                    [documents[i] for i in missing], normalize_embeddings=True
                ),
                dtype=np.float32,
            )
            for i, vector in zip(missing, vectors, strict=True):
                cached[keys[i]] = vector
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                # Only the current corpus is written back, so deleted
                # documents do not linger in the cache.
                np.savez(
                    cache_path,
                    keys=np.asarray(keys),
                    vectors=np.stack([cached[key] for key in keys]),
                )
        return np.stack([cached[key] for key in keys]).astype(np.float32)

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
