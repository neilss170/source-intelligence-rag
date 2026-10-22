import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)

from app.services.document_extraction import ExtractedPage
from app.services.text_chunking import chunk_pages

CONTENT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "the",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}

csv.field_size_limit(10 * 1024 * 1024)


def _terms(text: str) -> set[str]:
    values = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {
        value[:-1] if len(value) > 3 and value.endswith("s") else value
        for value in values
        if value not in CONTENT_STOPWORDS and len(value) > 1
    }


def _load_rows(dataset_dir: Path) -> tuple[dict[str, str], list[dict]]:
    with (dataset_dir / "documents.csv").open(encoding="utf-8-sig") as handle:
        documents = {row["index"]: row["text"] for row in csv.DictReader(handle)}

    rows: list[dict] = []
    for filename, label in (
        ("single_passage_answer_questions.csv", 1),
        ("multi_passage_answer_questions.csv", 1),
        ("no_answer_questions.csv", 0),
    ):
        with (dataset_dir / filename).open(encoding="utf-8-sig") as handle:
            rows.extend(
                {
                    "document_index": row["document_index"],
                    "question": row["question"],
                    "label": label,
                }
                for row in csv.DictReader(handle)
            )
    return documents, rows


def _build_features(
    documents: dict[str, str],
    rows: list[dict],
    model: SentenceTransformer,
    cross_encoder: CrossEncoder,
) -> np.ndarray:
    document_chunks = {
        document_id: [
            text
            for text in (
                chunk.text
                for chunk in chunk_pages((ExtractedPage(page=1, text=document_text),))
            )
        ]
        for document_id, document_text in documents.items()
    }
    chunk_embeddings = {
        document_id: np.asarray(
            model.encode(chunks, normalize_embeddings=True),
            dtype=np.float32,
        )
        for document_id, chunks in document_chunks.items()
    }
    question_embeddings = np.asarray(
        model.encode(
            [row["question"] for row in rows],
            prompt_name="query",
            normalize_embeddings=True,
        ),
        dtype=np.float32,
    )

    features: list[list[float]] = []
    for row, question_embedding in zip(rows, question_embeddings, strict=True):
        document_id = row["document_index"]
        raw_scores = chunk_embeddings[document_id] @ question_embedding
        ranked_indices = np.argsort(-raw_scores)
        scores = raw_scores[ranked_indices]
        padded = np.pad(scores[:3], (0, max(0, 3 - len(scores))), constant_values=0)
        best_index = int(ranked_indices[0])
        rerank_indices = ranked_indices[:3]
        rerank_scores = np.asarray(
            cross_encoder.predict(
                [
                    (row["question"], document_chunks[document_id][int(index)])
                    for index in rerank_indices
                ]
            ),
            dtype=np.float32,
        )
        question_terms = _terms(row["question"])
        best_terms = _terms(document_chunks[document_id][best_index])
        lexical_coverage = (
            len(question_terms & best_terms) / len(question_terms)
            if question_terms
            else 0.0
        )
        features.append(
            [
                float(padded[0]),
                float(padded[:3].mean()),
                float(padded[0] - padded[1]),
                lexical_coverage,
                float(len(question_terms)),
                float(rerank_scores.max()),
                float(rerank_scores.mean()),
            ]
        )
    return np.asarray(features, dtype=np.float32)


def _select_threshold(labels: np.ndarray, probabilities: np.ndarray) -> float:
    best_threshold = 0.5
    best_utility = -1.0
    for threshold in np.linspace(0.2, 0.8, 121):
        predicted = (probabilities >= threshold).astype(int)
        true_negative = np.sum((labels == 0) & (predicted == 0))
        true_positive = np.sum((labels == 1) & (predicted == 1))
        false_positive = np.sum((labels == 0) & (predicted == 1))
        utility = (true_negative + true_positive - 2 * false_positive) / len(labels)
        if utility > best_utility:
            best_utility = utility
            best_threshold = float(threshold)
    return best_threshold


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/metadata/answerability_model.json"),
    )
    args = parser.parse_args()

    documents, rows = _load_rows(args.dataset_dir)
    model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    features = _build_features(documents, rows, model, cross_encoder)
    labels = np.asarray([row["label"] for row in rows], dtype=np.int64)
    document_ids = np.asarray([int(row["document_index"]) for row in rows])

    test_mask = document_ids % 5 == 0
    train_mask = ~test_mask
    classifier = LogisticRegression(
        class_weight={0: 1.5, 1: 1.0},
        max_iter=1000,
        random_state=42,
    )
    classifier.fit(features[train_mask], labels[train_mask])
    train_probabilities = classifier.predict_proba(features[train_mask])[:, 1]
    threshold = _select_threshold(labels[train_mask], train_probabilities)
    test_probabilities = classifier.predict_proba(features[test_mask])[:, 1]
    predictions = (test_probabilities >= threshold).astype(int)

    precision, recall, f1, _ = precision_recall_fscore_support(
        labels[test_mask],
        predictions,
        average="binary",
        zero_division=0,
    )
    matrix = confusion_matrix(labels[test_mask], predictions, labels=[0, 1])
    report = {
        "feature_names": [
            "top_score",
            "mean_top3_score",
            "top_score_margin",
            "lexical_coverage",
            "question_term_count",
            "reranker_top_score",
            "reranker_mean_top3_score",
        ],
        "coefficients": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]),
        "threshold": threshold,
        "train_examples": int(train_mask.sum()),
        "test_examples": int(test_mask.sum()),
        "held_out_accuracy": float(accuracy_score(labels[test_mask], predictions)),
        "held_out_answerable_precision": float(precision),
        "held_out_answerable_recall": float(recall),
        "held_out_answerable_f1": float(f1),
        "held_out_confusion_matrix": {
            "true_no_answer": int(matrix[0, 0]),
            "false_answer": int(matrix[0, 1]),
            "false_abstain": int(matrix[1, 0]),
            "true_answer": int(matrix[1, 1]),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
