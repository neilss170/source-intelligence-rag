"""End-to-end evaluation over a mixed-format document corpus.

Retrieval (offline, no API key): recall@k, recall@1 and MRR over the fact
questions, plus how many passages the chain actually returns and how long it
takes.

Generation (``--generate``, needs CHAT_API_KEY): the full QueryService against
the configured model - answer accuracy, citation support, table accuracy,
abstention on unanswerable questions, and the workspace question.

    python scripts/evaluate_documents.py --name after
    python scripts/evaluate_documents.py --name after --generate
"""

import argparse
import contextlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "evaluation"))

from document_corpus import corpus, table_answers  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.query import QueryRequest  # noqa: E402
from app.services.document_ingestion import DocumentIngestionService  # noqa: E402
from app.services.uploaded_evidence_repository import (  # noqa: E402
    UploadedEvidenceRepository,
)

EVAL_SET = BACKEND_DIR / "evaluation" / "document_eval_set.json"
RESULTS_DIR = BACKEND_DIR / "evaluation" / "results"
TOP_K = 8
TEST_DATABASE_URL = (
    "postgresql+psycopg://si:si_dev_password@127.0.0.1:5433/source_intelligence_test"
)


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[‐-―-]", " ", text)
    text = re.sub(r"(?<=\d)[,\s  ](?=\d{3}\b)", "", text)
    text = re.sub(r"(?<=\d)[\s  ]+%", "%", text)
    return " ".join(text.split())


def numbers_in(text: str) -> list[float]:
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", normalize(text))]


def ingest(directory: Path) -> tuple[list, Path]:
    uploads = directory / "uploads"
    repository = UploadedEvidenceRepository(directory / "index" / "evidence.json")
    service = DocumentIngestionService(uploads, repository)
    for filename, content in corpus().items():
        service.ingest(filename, content)
    return repository.load(), uploads


def legacy_retriever(evidence):
    from app.services.adaptive_retriever import AdaptiveTopKRetriever
    from app.services.cross_encoder_reranker import CrossEncoderReranker
    from app.services.dense_retriever import DenseRetriever
    from app.services.entity_guard import EntityGuardRetriever
    from app.services.routed_retriever import RoutedDenseRetriever

    return AdaptiveTopKRetriever(
        CrossEncoderReranker(
            EntityGuardRetriever(
                RoutedDenseRetriever(DenseRetriever(evidence, minimum_score=0.35)),
                evidence,
            )
        )
    )


def production_retriever(evidence, cache_dir: Path):
    try:
        from app.core.dependencies import build_retriever
    except ImportError:
        return legacy_retriever(evidence)
    return build_retriever(
        evidence, get_settings(), model_backed=True, cache_dir=cache_dir
    )


def evaluate_retrieval(retriever, questions: list[dict]) -> dict:
    rows = []
    for item in questions:
        if item["kind"] != "fact":
            continue
        expected = [normalize(text) for text in item["expect_text"]]
        started = time.perf_counter()
        hits = retriever.search(item["question"], top_k=TOP_K)
        elapsed = (time.perf_counter() - started) * 1000
        texts = [normalize(f"{h.evidence.title} {h.evidence.text}") for h in hits]
        first = next(
            (rank for rank, text in enumerate(texts, 1) if expected[0] in text), None
        )
        rows.append(
            {
                "id": item["id"],
                "hits": len(hits),
                "recall_at_k": all(any(e in t for t in texts) for e in expected),
                "recall_at_1": first == 1,
                "reciprocal_rank": 1 / first if first else 0.0,
                "ms": round(elapsed),
            }
        )
    count = len(rows)
    return {
        "questions": count,
        "recall_at_k": round(sum(r["recall_at_k"] for r in rows) / count, 3),
        "recall_at_1": round(sum(r["recall_at_1"] for r in rows) / count, 3),
        "mrr": round(sum(r["reciprocal_rank"] for r in rows) / count, 3),
        "mean_passages_returned": round(statistics.mean(r["hits"] for r in rows), 2),
        "p50_ms": statistics.median(r["ms"] for r in rows),
        "misses": [r["id"] for r in rows if not r["recall_at_k"]],
        "rows": rows,
    }


def patient(client):
    """Wrap the chat client so a free-tier rate limit waits instead of failing."""
    from app.services.llm_client import LLMError

    complete = client.complete_text

    def complete_text(**kwargs):
        for attempt in range(8):
            try:
                return complete(**kwargs)
            except LLMError as exc:
                if "429" not in str(exc) and getattr(exc, "status_code", None) != 429:
                    raise
                time.sleep(15 + 5 * attempt)
        return complete(**kwargs)

    client.complete_text = complete_text
    return client


def build_service(evidence, uploads: Path, cache_dir: Path):
    settings = get_settings()
    if not settings.chat_api_key:
        raise SystemExit("--generate needs CHAT_API_KEY in backend/.env")
    from app.services.llm_client import ChatCompletionClient

    client = patient(
        ChatCompletionClient(
            api_key=settings.chat_api_key,
            api_base_url=settings.chat_api_base_url,
            model=settings.chat_model,
        )
    )
    try:
        from app.core.dependencies import build_query_service
    except ImportError:
        from app.services.general_knowledge import LocalGeneralKnowledgeProvider
        from app.services.llm_generator import LLMGroundedGenerator
        from app.services.query_service import QueryService

        return QueryService(
            legacy_retriever(evidence),
            LLMGroundedGenerator(client, workspace=evidence),
            LocalGeneralKnowledgeProvider(
                api_key=settings.chat_api_key,
                api_base_url=settings.chat_api_base_url,
                chat_model=settings.chat_model,
            ),
        )
    return build_query_service(
        evidence, settings, uploads_dir=uploads, cache_dir=cache_dir, client=client
    )


def evaluate_generation(service, questions: list[dict]) -> dict:
    answers = table_answers()
    rows = []
    for item in questions:
        started = time.perf_counter()
        response = service.query(QueryRequest(question=item["question"], top_k=TOP_K))
        elapsed = round((time.perf_counter() - started) * 1000)
        answer = normalize(response.answer)
        cited = [normalize(f"{c.title} {c.excerpt}") for c in response.citations]
        row = {
            "id": item["id"],
            "kind": item["kind"],
            "mode": response.mode.value,
            "citations": len(response.citations),
            "groundedness": response.groundedness_score,
            "ms": elapsed,
            "answer": response.answer,
        }
        if item["kind"] == "fact":
            expected = item.get("answer_contains") or [answers[item["compute"]]]
            row["correct"] = all(normalize(str(e)) in answer for e in expected)
            row["cited_support"] = any(
                normalize(item["expect_text"][0]) in text for text in cited
            )
            row["abstained"] = not response.citations
        elif item["kind"] == "table":
            expected = answers[item["compute"]]
            if isinstance(expected, str):
                row["correct"] = normalize(expected) in answer
            else:
                tolerance = max(0.6, abs(expected) * 0.005)
                row["correct"] = any(
                    abs(n - expected) <= tolerance for n in numbers_in(response.answer)
                )
            row["expected"] = expected
        elif item["kind"] == "unanswerable":
            row["correct"] = not response.citations and not response.grounded
        else:
            row["correct"] = all(
                normalize(e).replace("_", " ") in answer.replace("_", " ")
                for e in item["answer_contains"]
            )
        rows.append(row)
        print(f"  {item['id']} {'ok ' if row['correct'] else 'MISS'} {elapsed}ms")

    def share(kind, key="correct"):
        selected = [r for r in rows if r["kind"] == kind]
        return round(sum(bool(r[key]) for r in selected) / len(selected), 3)

    facts = [r for r in rows if r["kind"] == "fact"]
    return {
        "fact_accuracy": share("fact"),
        "fact_cited_support": share("fact", "cited_support"),
        "fact_false_abstention": share("fact", "abstained"),
        "table_accuracy": share("table"),
        "abstention_accuracy": share("unanswerable"),
        "meta_correct": share("meta"),
        "mean_groundedness_on_facts": round(
            statistics.mean(r["groundedness"] for r in facts), 3
        ),
        "p50_ms": statistics.median(r["ms"] for r in rows),
        "rows": rows,
    }


#: Thresholds for --gate (docs/REBUILD_PROMPT.md, section 12).
GATES = {"recall_at_k": 0.95, "mrr": 0.90}


@contextlib.contextmanager
def postgres_workspace(directory: Path):
    """The corpus indexed by the real worker pipeline into a throwaway
    workspace of the test database. Yields ``(session, workspace_id)``."""
    import uuid

    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from alembic import command
    from app.db.models import Document, User, Workspace
    from app.ingest.pipeline import index_document
    from app.ingest.storage import LocalFileStorage
    from app.ingest.validation import detect_kind

    url = os.environ.get("TEST_DATABASE_URL", TEST_DATABASE_URL)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    storage = LocalFileStorage(directory / "files")
    with Session(engine) as db:
        user = User(
            email=f"eval-{uuid.uuid4().hex[:8]}@example.invalid",
            name="Evaluation",
            password_hash="!",
        )
        user.workspaces.append(Workspace(name="Evaluation"))
        db.add(user)
        db.flush()
        workspace_id = user.workspaces[0].id
        documents = []
        for filename, content in corpus().items():
            kind = detect_kind(filename, content)
            document = Document(
                workspace_id=workspace_id,
                filename=filename,
                kind=kind,
                size_bytes=len(content),
                checksum=uuid.uuid4().hex,
                storage_key=storage.put(content, kind),
            )
            db.add(document)
            documents.append(document)
        db.commit()
        for document in documents:
            assert index_document(db, document.id, storage) == "ready"
        try:
            yield db, workspace_id
        finally:
            db.rollback()
            db.delete(db.get(User, user.id))
            db.commit()
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--legacy", action="store_true", help="old retrieval chain")
    parser.add_argument(
        "--backend",
        choices=["memory", "postgres"],
        default="memory",
        help="postgres: index into the test database and search it there",
    )
    parser.add_argument(
        "--gate", action="store_true", help="exit 1 if retrieval misses the gates"
    )
    args = parser.parse_args()

    questions = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    if args.backend == "postgres":
        from app.retrieval.pg import workspace_retriever

        with tempfile.TemporaryDirectory() as directory:
            with postgres_workspace(Path(directory)) as (db, workspace_id):
                report = {
                    "backend": "postgres",
                    "retrieval": evaluate_retrieval(
                        workspace_retriever(db, workspace_id, get_settings()),
                        questions,
                    ),
                }
        _finish(args, report)
        return

    with tempfile.TemporaryDirectory() as directory:
        evidence, uploads = ingest(Path(directory))
        cache_dir = Path(directory) / "index"
        chars = sum(len(e.text) for e in evidence)
        print(f"Corpus: {len(evidence)} passages, {chars} characters")
        retriever = (
            legacy_retriever(evidence)
            if args.legacy
            else production_retriever(evidence, cache_dir)
        )
        report = {
            "corpus": {"passages": len(evidence), "characters": chars},
            "retrieval": evaluate_retrieval(retriever, questions),
        }
        summary = {k: v for k, v in report["retrieval"].items() if k != "rows"}
        print("Retrieval:", json.dumps(summary))
        if args.generate:
            report["generation"] = evaluate_generation(
                build_service(evidence, uploads, cache_dir), questions
            )
            summary = {k: v for k, v in report["generation"].items() if k != "rows"}
            print("Generation:", json.dumps(summary))
    _finish(args, report)


def _finish(args, report: dict) -> None:
    if args.backend == "postgres":
        summary = {k: v for k, v in report["retrieval"].items() if k != "rows"}
        print("Retrieval:", json.dumps(summary))
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{args.name}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.gate:
        missed = {
            metric: report["retrieval"][metric]
            for metric, floor in GATES.items()
            if report["retrieval"][metric] < floor
        }
        if missed:
            print(f"GATE FAILED: {missed} (need {GATES})")
            sys.exit(1)
        print(f"Gate passed: {GATES}")


if __name__ == "__main__":
    main()
