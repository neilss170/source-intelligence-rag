from pathlib import Path

import numpy as np
import pytest

from app.models.query import QueryRequest, QueryScope, QueryType
from app.models.resume import EvidenceUnit, ResumeSection, SourceReference
from app.services import dense_retriever
from app.services.bm25_retriever import ScoredEvidence
from app.services.citation_support import SupportVerifier
from app.services.cross_encoder_reranker import CrossEncoderReranker
from app.services.llm_client import LLMError
from app.services.llm_generator import (
    INSUFFICIENT_MESSAGE,
    LLMGroundedGenerator,
    _arrange,
)
from app.services.query_service import QueryService
from app.services.table_store import TableQueryError, TableStore


def _evidence(suffix: str, text: str) -> EvidenceUnit:
    return EvidenceUnit(
        evidence_id=f"ev_doc_{suffix}",
        section=ResumeSection.DOCUMENT,
        title=f"report > {suffix}",
        text=text,
        source=SourceReference(
            document_id="doc_report",
            filename="report.md",
            page=1,
            source_text=text,
        ),
    )


class FakeClient:
    model = "test-model"

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.prompts = []

    def complete_text(self, *, system, user, max_tokens=3000):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def tables(tmp_path: Path) -> TableStore:
    path = tmp_path / "doc_ship_shipments.csv"
    path.write_text(
        "shipment_id,destination,cost_eur\nSH-1,Milan,100.5\nSH-2,Paris,200\n"
        "SH-3,Milan,50\n",
        encoding="utf-8",
    )
    return TableStore([("doc_ship", "shipments.csv", path)])


# -- table store ---------------------------------------------------------------


def test_table_store_types_columns_and_aggregates(tables: TableStore) -> None:
    result = tables.query(
        'SELECT SUM("cost_eur") AS total FROM "shipments" '
        "WHERE \"destination\" = 'Milan'"
    )

    assert result.columns == ("total",)
    assert result.rows == ((150.5,),)
    assert '"cost_eur" REAL' in tables.describe()
    assert "3 rows" in tables.describe()


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM shipments",
        "SELECT 1; DROP TABLE shipments",
        "ATTACH DATABASE 'x.db' AS x",
        "PRAGMA query_only = OFF",
        "WITH x AS (SELECT 1) INSERT INTO shipments VALUES ('a','b',1)",
    ],
)
def test_table_store_refuses_anything_but_reading(tables: TableStore, sql) -> None:
    with pytest.raises(TableQueryError):
        tables.query(sql)
    assert tables.query("SELECT COUNT(*) FROM shipments").rows == ((3,),)


def test_table_store_aborts_runaway_queries(tables: TableStore, monkeypatch) -> None:
    monkeypatch.setattr("app.services.table_store.QUERY_TIMEOUT_S", 0.05)
    with pytest.raises(TableQueryError):
        tables.query(
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
            "SELECT COUNT(*) FROM n"
        )


# -- generator -------------------------------------------------------------------


def test_sql_result_is_run_cited_and_returned_as_extra_evidence(tables) -> None:
    hits = [ScoredEvidence(_evidence("a", "SH-1 went to Milan."), 0.9)]
    client = FakeClient(
        'SQL: SELECT SUM("cost_eur") FROM "shipments"',
        "The total cost was 350.5 EUR [E2].",
    )
    generated = LLMGroundedGenerator(client, tables=tables).generate(
        "Total cost?", hits, QueryType.FACTUAL
    )

    assert "[E2] SQL: SELECT" in client.prompts[1]
    assert "350.5" in client.prompts[1]
    assert generated.answer == "The total cost was 350.5 EUR[1]."
    assert generated.evidence_ids == ["ev_sql_query_1"]
    assert generated.extra_evidence[0].source.filename == "shipments.csv"


def test_failed_sql_is_reported_back_to_the_model(tables) -> None:
    client = FakeClient(
        "```sql\nSELECT nope FROM missing\n```",
        "INSUFFICIENT_CONTEXT: the table has no such column.",
    )
    generated = LLMGroundedGenerator(client, tables=tables).generate(
        "Total?", [], QueryType.FACTUAL
    )

    assert "--- QUERY FAILED ---" in client.prompts[1]
    assert generated.abstained


def test_insufficient_context_becomes_a_fixed_abstention() -> None:
    client = FakeClient("INSUFFICIENT_CONTEXT: salaries are not in the documents.")
    generated = LLMGroundedGenerator(client).generate(
        "CEO salary?",
        [ScoredEvidence(_evidence("a", "Fleet of 214."), 0.4)],
        QueryType.FACTUAL,
    )

    assert generated.abstained and generated.insufficient_evidence
    assert generated.answer.startswith(INSUFFICIENT_MESSAGE)
    assert "salaries" in generated.answer


def test_rate_limit_retries_with_the_best_half_of_the_passages() -> None:
    hits = [
        ScoredEvidence(_evidence(str(i), f"Fact number {i}."), score)
        for i, score in enumerate([0.1, 0.9, 0.5, 0.7, 0.2, 0.3])
    ]
    client = FakeClient(
        LLMError("Chat provider returned 429", status_code=429),
        "Fact one [E1].",
    )
    generated = LLMGroundedGenerator(client).generate("q", hits, QueryType.FACTUAL)

    assert len(client.prompts) == 2
    assert client.prompts[0].count("[E") == 6
    retried = client.prompts[1]
    assert retried.count("[E") == 3
    assert "Fact number 1." in retried and "Fact number 0." not in retried
    assert generated.evidence_ids


def test_passages_are_arranged_best_at_the_edges() -> None:
    hits = [
        ScoredEvidence(_evidence(name, name), score)
        for name, score in [("c", 0.3), ("a", 0.9), ("e", 0.1), ("b", 0.7), ("d", 0.2)]
    ]
    order = [hit.evidence.text for hit in _arrange(hits)]

    assert order == ["a", "c", "e", "d", "b"]


def test_unscored_passages_keep_document_order() -> None:
    hits = [ScoredEvidence(_evidence(n, n), 1.0) for n in "xyz"]
    assert [h.evidence.text for h in _arrange(hits)] == ["x", "y", "z"]


def test_whole_workspace_is_ranked_unless_a_summary_is_asked_for() -> None:
    class Ranker:
        def score(self, query, evidence):
            return [0.1, 0.9]

    workspace = [_evidence("a", "first"), _evidence("b", "second")]
    generator = LLMGroundedGenerator(FakeClient(), workspace=workspace, ranker=Ranker())

    ranked = generator.whole_workspace("what is second?")
    in_order = generator.whole_workspace("summarise the report")

    assert [h.evidence.text for h in ranked] == ["second", "first"]
    assert [h.evidence.text for h in in_order] == ["first", "second"]


# -- query service --------------------------------------------------------------


class StaticRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.top_k = None

    def search(self, query, *, top_k=5):
        self.top_k = top_k
        return self.hits


def test_abstention_is_a_workspace_answer_not_general_chat() -> None:
    class FailingGeneral:
        def answer(self, question, history):
            raise AssertionError("must not fall back to general chat")

    retriever = StaticRetriever([ScoredEvidence(_evidence("a", "Fleet of 214."), 0.4)])
    service = QueryService(
        retriever,
        LLMGroundedGenerator(FakeClient("INSUFFICIENT_CONTEXT: not covered.")),
        FailingGeneral(),
        min_top_k=8,
    )
    response = service.query(QueryRequest(question="CEO salary?", top_k=2))

    assert retriever.top_k == 8
    assert response.mode.value == "workspace"
    assert response.grounded is False
    assert response.answer.startswith(INSUFFICIENT_MESSAGE)


def test_sql_citation_reaches_the_response(tables) -> None:
    service = QueryService(
        StaticRetriever([]),
        LLMGroundedGenerator(
            FakeClient("SQL: SELECT COUNT(*) FROM shipments", "There were 3 [E1]."),
            tables=tables,
        ),
    )
    response = service.query(
        QueryRequest(question="How many shipments?", scope=QueryScope.WORKSPACE)
    )

    assert response.grounded
    assert response.citations[0].title == "SQL query on shipments.csv"
    assert response.citations[0].page is None


def test_verifier_sets_groundedness_and_flags_unsupported_claims() -> None:
    class NLI:
        config = type("Config", (), {"id2label": {0: "contradiction", 1: "entailment"}})

        def predict(self, pairs, apply_softmax=True):
            return [
                [0.1, 0.9] if "214" in claim else [0.95, 0.05]
                for premise, claim in pairs
            ]

    retriever = StaticRetriever(
        [ScoredEvidence(_evidence("a", "Fleet of 214 trucks."), 0.9)]
    )
    service = QueryService(
        retriever,
        LLMGroundedGenerator(
            FakeClient("The fleet has 214 trucks [E1]. It also owns 90 ships [E1].")
        ),
        verifier=SupportVerifier(model=NLI()),
    )
    response = service.query(QueryRequest(question="Fleet size?"))

    assert response.groundedness_score == 0.5
    assert response.unsupported_claims == ["It also owns 90 ships."]


# -- retrieval ------------------------------------------------------------------


def test_reranker_reports_probabilities_and_keeps_a_minimum() -> None:
    class Scorer:
        def predict(self, pairs):
            return [4.0, -6.0, -7.0]

    candidates = [
        ScoredEvidence(_evidence(n, n), 0.5) for n in ("good", "weak", "weaker")
    ]
    reranker = CrossEncoderReranker(
        StaticRetriever(candidates),
        scorer=Scorer(),
        probabilities=True,
        min_score=0.5,
        min_keep=2,
    )
    hits = reranker.search("q", top_k=3)

    assert [h.evidence.text for h in hits] == ["good", "weak"]
    assert 0.98 < hits[0].score < 1.0


def test_embeddings_are_cached_by_text(tmp_path: Path, monkeypatch) -> None:
    encoded = []

    class Encoder:
        def encode(self, texts, **kwargs):
            encoded.extend(texts)
            return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr(dense_retriever, "load_encoder", lambda name: Encoder())
    cache = tmp_path / "embeddings.npz"
    first = [_evidence("a", "alpha"), _evidence("b", "beta")]

    dense_retriever.DenseRetriever(first, cache_path=cache)
    dense_retriever.DenseRetriever([*first, _evidence("c", "gamma")], cache_path=cache)

    assert len(encoded) == 3
    assert "gamma" in encoded[-1]


def test_verifier_checks_claims_against_sentences_not_whole_passages() -> None:
    premises = []

    class NLI:
        config = type("Config", (), {"id2label": {0: "contradiction", 1: "entailment"}})

        def predict(self, pairs, apply_softmax=True):
            premises.extend(premise for premise, _ in pairs)
            return [
                [0.0, 1.0] if "214" in premise else [1.0, 0.0] for premise, _ in pairs
            ]

    passage = " ".join(f"Unrelated sentence {i} about storage." for i in range(12))
    passage += " The company runs a fleet of 214 trucks."
    report = SupportVerifier(model=NLI()).verify(
        "The fleet has 214 trucks[1].", {1: passage}
    )

    assert report.score == 1.0
    assert len(premises) <= 5
    assert all(len(premise) < 120 for premise in premises)


def test_claims_citing_only_table_rows_are_not_judged_by_nli() -> None:
    class NLI:
        config = type("Config", (), {"id2label": {0: "contradiction", 1: "entailment"}})

        def predict(self, pairs, apply_softmax=True):
            raise AssertionError("record passages must not reach the NLI model")

    row = EvidenceUnit(
        evidence_id="ev_upload_rows_001",
        section=ResumeSection.DOCUMENT,
        title="shipments",
        text="shipment_id: SH-0042\ndestination: Paris",
        source=SourceReference(
            document_id="doc_rows",
            filename="shipments.csv",
            page=42,
            source_text="shipment_id: SH-0042\ndestination: Paris",
        ),
    )
    service = QueryService(
        StaticRetriever([ScoredEvidence(row, 0.9)]),
        LLMGroundedGenerator(FakeClient("SH-0042 was going to Paris [E1].")),
        verifier=SupportVerifier(model=NLI()),
    )
    response = service.query(QueryRequest(question="Where was SH-0042 going?"))

    assert response.grounded
    assert response.groundedness_score == 1.0
    assert response.unsupported_claims == []


def test_exhausted_quota_is_reported_instead_of_a_silent_rule_based_answer() -> None:
    quota = LLMError("Chat provider returned 429", status_code=429)
    quota.retry_after = 602.0
    hits = [ScoredEvidence(_evidence(str(i), f"Fact {i}."), 0.5) for i in range(2)]

    generated = LLMGroundedGenerator(FakeClient(quota)).generate(
        "q", hits, QueryType.FACTUAL
    )

    assert generated.from_model and generated.insufficient_evidence
    assert "usage limit has been reached (test-model)" in generated.answer
    assert "about 10 minutes" in generated.answer


def test_client_switches_to_the_fallback_model_when_quota_runs_out(monkeypatch) -> None:
    from app.services.llm_client import ChatCompletionClient

    calls = []

    def post(self, payload):
        calls.append(payload["model"])
        if payload["model"] == "big":
            error = LLMError("Chat provider returned 429", status_code=429)
            error.retry_after = 600.0
            raise error
        return "answer"

    monkeypatch.setattr(ChatCompletionClient, "_post", post)
    client = ChatCompletionClient(api_key="k", model="big", fallback_models=("small",))

    assert client.complete_text(system="s", user="u") == "answer"
    assert client.model == "small"
    assert client.complete_text(system="s", user="u") == "answer"
    assert calls == ["big", "small", "small"]


def test_quota_message_appears_only_when_every_model_is_exhausted(monkeypatch) -> None:
    from app.services.llm_client import ChatCompletionClient

    def post(self, payload):
        error = LLMError("Chat provider returned 429", status_code=429)
        error.retry_after = 300.0
        raise error

    monkeypatch.setattr(ChatCompletionClient, "_post", post)
    client = ChatCompletionClient(api_key="k", model="big", fallback_models=("small",))
    hits = [ScoredEvidence(_evidence("a", "Fact."), 0.5)]

    generated = LLMGroundedGenerator(client).generate("q", hits, QueryType.FACTUAL)

    assert "usage limit has been reached" in generated.answer
