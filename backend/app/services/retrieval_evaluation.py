from dataclasses import dataclass
from math import ceil
from time import perf_counter
from typing import Protocol

from app.models.evaluation import EvaluationCase


class Retriever(Protocol):
    def search(self, query: str, *, top_k: int = 5) -> list: ...


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    question: str
    relevant_ids: tuple[str, ...]
    retrieved_ids: tuple[str, ...]
    precision: float
    recall: float
    latency_ms: float


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    context_precision: float
    context_recall: float
    p95_retrieval_latency_ms: float
    cases: tuple[CaseResult, ...]


def evaluate_retriever(
    retriever: Retriever,
    cases: list[EvaluationCase],
    *,
    top_k: int = 5,
) -> RetrievalEvaluation:
    results: list[CaseResult] = []
    for case in cases:
        started = perf_counter()
        hits = retriever.search(case.question, top_k=top_k)
        latency_ms = (perf_counter() - started) * 1000
        retrieved_ids = tuple(hit.evidence.evidence_id for hit in hits)
        relevant = set(case.relevant_evidence_ids)
        retrieved = set(retrieved_ids)
        matches = relevant & retrieved
        if relevant:
            recall = len(matches) / len(relevant)
            precision = len(matches) / len(retrieved) if retrieved else 0.0
        else:
            recall = 1.0
            precision = 1.0 if not retrieved else 0.0
        results.append(
            CaseResult(
                case_id=case.id,
                question=case.question,
                relevant_ids=tuple(case.relevant_evidence_ids),
                retrieved_ids=retrieved_ids,
                precision=precision,
                recall=recall,
                latency_ms=latency_ms,
            )
        )

    latencies = sorted(result.latency_ms for result in results)
    p95_index = max(0, ceil(0.95 * len(latencies)) - 1)
    return RetrievalEvaluation(
        context_precision=sum(result.precision for result in results) / len(results),
        context_recall=sum(result.recall for result in results) / len(results),
        p95_retrieval_latency_ms=latencies[p95_index],
        cases=tuple(results),
    )


evaluate_bm25 = evaluate_retriever
