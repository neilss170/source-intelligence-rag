import json
from pathlib import Path

from app.services.dense_retriever import DenseRetriever
from app.services.evaluation_repository import EvaluationRepository
from app.services.evidence_repository import EvidenceRepository
from app.services.retrieval_evaluation import evaluate_retriever
from app.services.routed_retriever import RoutedDenseRetriever

EVALUATION_DIR = Path(__file__).resolve().parents[1] / "evaluation"


def main() -> None:
    evidence = EvidenceRepository(EVALUATION_DIR / "reference_evidence.json").load()
    cases = EvaluationRepository(EVALUATION_DIR / "eval_set.json").load()
    retriever = RoutedDenseRetriever(DenseRetriever(evidence, minimum_score=0.35))
    evaluation = evaluate_retriever(retriever, cases, top_k=3)
    failures = sorted(
        evaluation.cases,
        key=lambda case: (case.recall, case.precision, case.case_id),
    )[:5]
    print(
        json.dumps(
            {
                "configuration": {
                    "strategy": "metadata_routed_dense",
                    "model": "BAAI/bge-small-en-v1.5",
                    "top_k": 3,
                    "minimum_score": 0.35,
                },
                "metrics": {
                    "context_precision": evaluation.context_precision,
                    "context_recall": evaluation.context_recall,
                    "p95_retrieval_latency_ms": evaluation.p95_retrieval_latency_ms,
                },
                "failures": [
                    {
                        "id": case.case_id,
                        "question": case.question,
                        "relevant": case.relevant_ids,
                        "retrieved": case.retrieved_ids,
                        "precision": case.precision,
                        "recall": case.recall,
                    }
                    for case in failures
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
