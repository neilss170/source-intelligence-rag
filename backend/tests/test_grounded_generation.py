from dataclasses import dataclass
from pathlib import Path

import pytest

from app.models.query import GeneratedAnswer, QueryRequest, QueryType
from app.models.resume import EvidenceUnit, ResumeSection, SourceReference
from app.services.citation_validation import (
    UnsupportedCitationError,
    validate_citations,
)
from app.services.evidence_repository import EvidenceRepository
from app.services.grounded_generator import (
    INSUFFICIENT_ANSWER,
    GroundedGenerator,
)
from app.services.query_service import QueryService

EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "reference_evidence.json"
)


@dataclass(frozen=True)
class Hit:
    evidence: object
    score: float = 0.9


class StubRetriever:
    def __init__(self, hits: list[Hit]) -> None:
        self._hits = hits

    def search(self, query: str, *, top_k: int = 5) -> list[Hit]:
        return self._hits[:top_k]


def test_empty_context_returns_honest_fallback() -> None:
    answer = GroundedGenerator().generate(
        "Does the resume list React?",
        [],
        QueryType.SKILL,
    )

    assert answer.insufficient_evidence is True
    assert answer.evidence_ids == []
    assert answer.answer.startswith(
        "No — React is not mentioned in the indexed documents."
    )


def test_generated_answer_uses_only_retrieved_evidence() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    hit = Hit(evidence=evidence[4])

    response = QueryService(
        StubRetriever([hit]),
        GroundedGenerator(),
    ).query(QueryRequest(question="Describe the diabetes project."))

    assert response.grounded is True
    assert response.groundedness_score == 1.0
    assert [citation.evidence_id for citation in response.citations] == [
        evidence[4].evidence_id
    ]
    assert evidence[4].text.lower() in response.answer.lower()


def test_rejects_evidence_id_not_in_retrieved_context() -> None:
    answer = GeneratedAnswer(
        answer="Unsupported answer.",
        evidence_ids=["ev_project_unknown"],
    )

    with pytest.raises(UnsupportedCitationError):
        validate_citations(answer, {"ev_project_diabetes_001"})


def test_yes_no_and_descriptive_questions_do_not_repeat_same_answer() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    hit = Hit(evidence=evidence[4])
    generator = GroundedGenerator()

    yes_no = generator.generate(
        "Has Neil worked with Flask?",
        [hit],
        QueryType.SKILL,
    )
    descriptive = generator.generate(
        "Describe the diabetes project.",
        [hit],
        QueryType.SYNTHESIS,
    )

    assert yes_no.answer.startswith("Yes —")
    assert not descriptive.answer.startswith("Yes —")
    assert yes_no.answer != descriptive.answer


def test_skill_question_lists_only_verified_technologies() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    skill_evidence = next(
        item for item in evidence if item.evidence_id == "ev_skills_programming_001"
    )

    answer = GroundedGenerator().generate(
        "Which programming languages are listed?",
        [Hit(evidence=skill_evidence)],
        QueryType.SKILL,
    )

    assert answer.answer == "The indexed documents list Java, Python, and C."


def test_project_specific_question_excludes_other_projects() -> None:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    diabetes = next(
        item for item in evidence if item.evidence_id == "ev_project_diabetes_001"
    )
    delivery = next(
        item for item in evidence if item.evidence_id == "ev_project_delivery_001"
    )

    answer = GroundedGenerator().generate(
        "Describe the diabetes project.",
        [Hit(evidence=diabetes), Hit(evidence=delivery)],
        QueryType.SYNTHESIS,
    )

    assert diabetes.text.lower() in answer.answer.lower()
    assert delivery.text.lower() not in answer.answer.lower()
    assert answer.evidence_ids == [diabetes.evidence_id]


def test_indirect_education_question_extracts_only_institutions() -> None:
    evidence = EvidenceUnit(
        evidence_id="ev_document_resume_001",
        section=ResumeSection.DOCUMENT,
        title="Resume",
        text=(
            "Education Bachelor of Engineering 2022-2026 "
            "R.V. College of Engineering, Bengaluru "
            "Senior Secondary 2022 Maheshwari Public School JN, Jaipur "
            "Projects Diabetes Prediction Model developed with Flask."
        ),
        source=SourceReference(
            document_id="doc_resume",
            filename="resume.pdf",
            page=1,
            source_text="Resume source",
        ),
    )

    answer = GroundedGenerator().generate(
        "Where have they studied?",
        [Hit(evidence=evidence)],
        QueryType.FACTUAL,
    )

    assert answer.answer == (
        "They studied at the following institutions:\n\n"
        "College: R.V. College of Engineering, Bengaluru\n"
        "School: Maheshwari Public School JN, Jaipur"
    )
    assert "Diabetes" not in answer.answer


def test_simple_factual_question_does_not_dump_entire_chunk() -> None:
    evidence = EvidenceUnit(
        evidence_id="ev_document_policy_001",
        section=ResumeSection.DOCUMENT,
        title="Policy",
        text=(
            "Returns are accepted within 30 days with proof of purchase. "
            "The warehouse operates from Monday to Friday. "
            "Customer support is available by email."
        ),
        source=SourceReference(
            document_id="doc_policy",
            filename="policy.txt",
            page=1,
            source_text="Policy source",
        ),
    )

    answer = GroundedGenerator().generate(
        "What is the return period?",
        [Hit(evidence=evidence)],
        QueryType.FACTUAL,
    )

    assert answer.answer == (
        "Returns are accepted within 30 days with proof of purchase."
    )
    assert "warehouse" not in answer.answer


def test_unsupported_relation_returns_missing_data_without_citations() -> None:
    evidence = EvidenceUnit(
        evidence_id="ev_document_profile_001",
        section=ResumeSection.DOCUMENT,
        title="Profile",
        text="Neil studies computer science and develops machine-learning projects.",
        source=SourceReference(
            document_id="doc_profile",
            filename="profile.txt",
            page=1,
            source_text="Profile source",
        ),
    )

    response = QueryService(
        StubRetriever([Hit(evidence=evidence)]),
        GroundedGenerator(),
    ).query(QueryRequest(question="Who are Neil's friends?"))

    assert response.answer == INSUFFICIENT_ANSWER
    assert response.grounded is False
    assert response.groundedness_score == 0.0
    assert response.citations == []


def test_yes_no_question_requires_subject_evidence() -> None:
    evidence = EvidenceUnit(
        evidence_id="ev_document_resume_002",
        section=ResumeSection.DOCUMENT,
        title="Resume",
        text="Neil uses Python for machine-learning projects.",
        source=SourceReference(
            document_id="doc_resume",
            filename="resume.pdf",
            page=1,
            source_text="Resume source",
        ),
    )

    answer = GroundedGenerator().generate(
        "Can you name mechanical keyboards?",
        [Hit(evidence=evidence)],
        QueryType.FACTUAL,
    )

    assert answer.answer == INSUFFICIENT_ANSWER
    assert answer.insufficient_evidence is True
