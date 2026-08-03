from collections import Counter
from dataclasses import dataclass
from math import log

from app.models.resume import EvidenceUnit
from app.services.tokenization import tokenize


@dataclass(frozen=True, slots=True)
class ScoredEvidence:
    evidence: EvidenceUnit
    score: float


class BM25Retriever:
    def __init__(
        self,
        evidence: list[EvidenceUnit],
        *,
        k1: float = 1.5,
        b: float = 0.75,
        minimum_score: float = 0.1,
    ) -> None:
        if not evidence:
            raise ValueError("BM25 requires at least one evidence unit")
        self._evidence = evidence
        self._k1 = k1
        self._b = b
        self._minimum_score = minimum_score
        self._documents = [
            tokenize(
                " ".join(
                    [
                        item.title,
                        item.organization or "",
                        " ".join(item.technologies),
                        item.text,
                    ]
                )
            )
            for item in evidence
        ]
        self._term_frequencies = [Counter(document) for document in self._documents]
        self._document_lengths = [len(document) for document in self._documents]
        self._average_document_length = sum(self._document_lengths) / len(
            self._document_lengths
        )
        document_frequency: Counter[str] = Counter()
        for document in self._documents:
            document_frequency.update(set(document))
        document_count = len(self._documents)
        self._idf = {
            term: log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, *, top_k: int = 5) -> list[ScoredEvidence]:
        query_terms = tokenize(query)
        if not query_terms:
            return []

        scored: list[ScoredEvidence] = []
        for index, evidence in enumerate(self._evidence):
            score = self._score_document(query_terms, index)
            if score >= self._minimum_score:
                scored.append(ScoredEvidence(evidence=evidence, score=score))

        scored.sort(key=lambda hit: (-hit.score, hit.evidence.evidence_id))
        return scored[:top_k]

    def _score_document(self, query_terms: list[str], index: int) -> float:
        frequencies = self._term_frequencies[index]
        document_length = self._document_lengths[index]
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            length_normalization = (
                1
                - self._b
                + self._b * (document_length / self._average_document_length)
            )
            score += (
                self._idf.get(term, 0.0)
                * frequency
                * (self._k1 + 1)
                / (frequency + self._k1 * length_normalization)
            )
        return score
