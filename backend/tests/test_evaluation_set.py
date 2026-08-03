from pathlib import Path

from app.services.evaluation_repository import EvaluationRepository
from app.services.evidence_repository import EvidenceRepository

EVALUATION_DIR = Path(__file__).resolve().parents[1] / "evaluation"


def test_eval_set_is_frozen_valid_and_references_known_evidence() -> None:
    cases = EvaluationRepository(EVALUATION_DIR / "eval_set.json").load()
    evidence = EvidenceRepository(EVALUATION_DIR / "reference_evidence.json").load()
    evidence_ids = {item.evidence_id for item in evidence}

    assert len(cases) == 25
    assert len({case.id for case in cases}) == 25
    assert any(not case.relevant_evidence_ids for case in cases)
    assert {
        "factual",
        "skill",
        "synthesis",
        "behavioral",
        "evaluative",
    }.issubset({case.query_type.value for case in cases})
    assert all(
        relevant_id in evidence_ids
        for case in cases
        for relevant_id in case.relevant_evidence_ids
    )
