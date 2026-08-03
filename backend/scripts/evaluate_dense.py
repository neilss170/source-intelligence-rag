import argparse
import json
from pathlib import Path

from app.services.dense_retriever import DenseRetriever
from app.services.evaluation_repository import EvaluationRepository
from app.services.evidence_repository import EvidenceRepository
from app.services.retrieval_evaluation import evaluate_retriever

EVALUATION_DIR = Path(__file__).resolve().parents[1] / "evaluation"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--minimum-score", type=float, default=0.35)
    args = parser.parse_args()
    evidence = EvidenceRepository(EVALUATION_DIR / "reference_evidence.json").load()
    cases = EvaluationRepository(EVALUATION_DIR / "eval_set.json").load()
    evaluation = evaluate_retriever(
        DenseRetriever(evidence, minimum_score=args.minimum_score),
        cases,
        top_k=args.top_k,
    )
    failures = sorted(
        evaluation.cases,
        key=lambda case: (case.recall, case.precision, case.case_id),
    )[:5]
    print(
        json.dumps(
            {
                "configuration": {
                    "strategy": "dense",
                    "model": "BAAI/bge-small-en-v1.5",
                    "top_k": args.top_k,
                    "minimum_score": args.minimum_score,
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
