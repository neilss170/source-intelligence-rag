from pathlib import Path

from app.services.evidence_repository import EvidenceRepository

REFERENCE_EVIDENCE = (
    Path(__file__).resolve().parents[1] / "evaluation" / "reference_evidence.json"
)


def test_reference_evidence_is_valid_unique_and_private() -> None:
    evidence = EvidenceRepository(REFERENCE_EVIDENCE).load()
    evidence_ids = [item.evidence_id for item in evidence]

    assert len(evidence) >= 15
    assert len(evidence_ids) == len(set(evidence_ids))
    assert all(item.source.page == 1 for item in evidence)
    assert all("[EMAIL" not in item.text for item in evidence)
    assert all("[PHONE" not in item.text for item in evidence)


def test_reference_evidence_does_not_invent_employment() -> None:
    evidence = EvidenceRepository(REFERENCE_EVIDENCE).load()

    assert all(item.section.value != "experience" for item in evidence)
