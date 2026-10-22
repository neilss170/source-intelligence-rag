"""Retrieval over Postgres (milestone 3).

Ranking quality is measured by the evaluation gate with the real models
(``scripts/evaluate_documents.py --backend postgres --gate``). These tests
pin the behaviour around it: workspace scoping, keyword semantics, and the
whole-workspace and table helpers.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Workspace
from app.retrieval import pg
from app.retrieval.pg import (
    PgDenseRetriever,
    PgKeywordRetriever,
    workspace_files,
    workspace_passages,
    workspace_size,
    workspace_tables,
)

REPORT = (
    b"# Annual report\n\n## Safety\n\nLost-time incidents fell to 7 in 2025. "
    b"Forklift training is mandatory every 18 months.\n\n## Fleet\n\n"
    b"The company operates 214 trucks."
)
CSV = b"shipment_id,destination,cost_eur\nSH-0042,Milan,100.5\nSH-0043,Paris,200\n"


@pytest.fixture
def workspaces(make_client, sign_up, ingestion, fake_encoder, monkeypatch, db):
    """Alice and Bob, each with documents indexed into their own workspace."""
    monkeypatch.setattr(pg, "load_encoder", lambda name: fake_encoder)
    alice, bob = make_client(), make_client()
    sign_up(alice, "alice@example.com")
    sign_up(bob, "bob@example.com")
    alice.post(
        "/api/documents",
        files=[
            ("files", ("report.md", REPORT, "text/markdown")),
            ("files", ("shipments.csv", CSV, "text/csv")),
        ],
    )
    bob.post(
        "/api/documents",
        files=[("files", ("bob.txt", b"Bob's forklift notes mention SH-0042.", "x"))],
    )
    with Session(db) as session:
        owner = {
            email: workspace_id
            for email, workspace_id in session.execute(
                select(User.email, Workspace.id).join(
                    Workspace, Workspace.owner_id == User.id
                )
            )
        }
    return owner["alice@example.com"], owner["bob@example.com"]


def _titles(hits):
    return [hit.evidence.title for hit in hits]


def test_keyword_search_needs_any_word_not_every_word(workspaces, db) -> None:
    alice, _ = workspaces
    with Session(db) as session:
        hits = PgKeywordRetriever(session, alice).search(
            "how often must forklift drivers be retrained?"
        )

    assert _titles(hits)[0] == "report > Annual report > Safety"


def test_exact_identifiers_are_found_by_keyword(workspaces, db) -> None:
    alice, _ = workspaces
    with Session(db) as session:
        hits = PgKeywordRetriever(session, alice).search("Where was SH-0042 going?")

    assert "SH-0042" in hits[0].evidence.text
    assert all("SH-0043" not in hit.evidence.text for hit in hits[:1])


@pytest.mark.parametrize("retriever", ["keyword", "dense"])
def test_search_never_crosses_workspaces(workspaces, db, retriever) -> None:
    alice, bob = workspaces
    with Session(db) as session:
        make = {
            "keyword": lambda w: PgKeywordRetriever(session, w),
            "dense": lambda w: PgDenseRetriever(
                session, w, model_name="fake", minimum_score=-1.0
            ),
        }[retriever]
        bobs = make(bob).search("forklift SH-0042 trucks", top_k=50)
        alices = make(alice).search("forklift SH-0042 trucks", top_k=50)

    assert {hit.evidence.source.filename for hit in bobs} == {"bob.txt"}
    assert "bob.txt" not in {hit.evidence.source.filename for hit in alices}


def test_dense_search_respects_the_score_floor(workspaces, db) -> None:
    alice, _ = workspaces
    with Session(db) as session:
        everything = PgDenseRetriever(
            session, alice, model_name="fake", minimum_score=-1.0
        ).search("trucks", top_k=50)
        nothing = PgDenseRetriever(
            session, alice, model_name="fake", minimum_score=1.01
        ).search("trucks", top_k=50)

    assert len(everything) == 4  # two report sections, two CSV rows
    assert [h.score for h in everything] == sorted(
        (h.score for h in everything), reverse=True
    )
    assert nothing == []


def test_empty_or_stopword_queries_return_nothing(workspaces, db) -> None:
    alice, _ = workspaces
    with Session(db) as session:
        assert PgKeywordRetriever(session, alice).search("the of and") == []
        assert (
            PgDenseRetriever(session, alice, model_name="f", minimum_score=0).search(
                "  "
            )
            == []
        )


def test_whole_workspace_helpers(workspaces, db) -> None:
    alice, _ = workspaces
    with Session(db) as session:
        passages = workspace_passages(session, alice)
        size = workspace_size(session, alice)
        files = workspace_files(session, alice)

    assert [p.title for p in passages][:2] == [
        "report > Annual report > Safety",
        "report > Annual report > Fleet",
    ]
    assert size == sum(len(p.text) for p in passages)
    assert [(f.filename, f.status) for f in files] == [
        ("report.md", "ready"),
        ("shipments.csv", "ready"),
    ]
    assert passages[0].evidence_id.startswith("ev_")


def test_tables_load_from_the_database(workspaces, db) -> None:
    alice, bob = workspaces
    with Session(db) as session:
        alices = workspace_tables(session, alice)
        bobs = workspace_tables(session, bob)

    result = alices.query('SELECT SUM("cost_eur") FROM "shipments"')
    assert result.rows == ((300.5,),)
    assert not bobs
