from datetime import date

import pytest
from pydantic import ValidationError

from app.models.query import GeneratedAnswer, QueryRoute, QueryType
from app.models.resume import CandidateResume, DateRange


def test_candidate_resume_normalizes_duplicate_skills() -> None:
    resume = CandidateResume(
        candidate_name="Sample Candidate",
        skills=["Python", " Python ", "", "FastAPI", "Python"],
    )

    assert resume.skills == ["Python", "FastAPI"]


def test_query_route_rejects_reversed_date_range() -> None:
    with pytest.raises(ValidationError, match="date_from cannot be later"):
        QueryRoute(
            query_type=QueryType.FACTUAL,
            date_from=2025,
            date_to=2023,
        )


def test_grounded_answer_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="at least one evidence ID"):
        GeneratedAnswer(
            answer="The candidate has Python experience.",
            evidence_ids=[],
            insufficient_evidence=False,
        )


def test_insufficient_answer_can_have_no_evidence() -> None:
    answer = GeneratedAnswer(
        answer="That is not covered in the candidate's resume.",
        insufficient_evidence=True,
    )

    assert answer.evidence_ids == []


def test_date_range_accepts_partial_resume_dates() -> None:
    period = DateRange(start=date(2024, 1, 1), label="2024 — Present")

    assert period.end is None
