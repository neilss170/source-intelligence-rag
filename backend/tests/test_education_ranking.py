from dataclasses import dataclass
from pathlib import Path

from app.services.evidence_repository import EvidenceRepository
from app.services.routed_retriever import rank_education_hits

EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "reference_evidence.json"
)


@dataclass(frozen=True)
class Hit:
    evidence: object
    score: float


def _education_hits() -> list[Hit]:
    evidence = EvidenceRepository(EVIDENCE_PATH).load()
    education = [item for item in evidence if item.section.value == "education"]
    return [
        Hit(evidence=education[1], score=0.9),
        Hit(evidence=education[2], score=0.8),
        Hit(evidence=education[0], score=0.6),
    ]


def test_college_question_prioritizes_bachelors_entry() -> None:
    ranked = rank_education_hits("Which college does Neil attend?", _education_hits())

    assert ranked[0].evidence.evidence_id == "ev_education_001"


def test_school_question_prioritizes_secondary_entries() -> None:
    ranked = rank_education_hits("Which school did Neil attend?", _education_hits())

    assert {
        ranked[0].evidence.evidence_id,
        ranked[1].evidence.evidence_id,
    } == {"ev_education_002", "ev_education_003"}
