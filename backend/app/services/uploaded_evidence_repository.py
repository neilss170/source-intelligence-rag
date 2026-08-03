import json
from pathlib import Path

from pydantic import TypeAdapter

from app.models.resume import EvidenceUnit

EVIDENCE_LIST_ADAPTER = TypeAdapter(list[EvidenceUnit])


class UploadedEvidenceRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[EvidenceUnit]:
        if not self._path.exists():
            return []
        return EVIDENCE_LIST_ADAPTER.validate_python(
            json.loads(self._path.read_text(encoding="utf-8"))
        )

    def save(self, evidence: list[EvidenceUnit]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                [item.model_dump(mode="json") for item in evidence],
                indent=2,
            ),
            encoding="utf-8",
        )

    def delete_document(self, document_id: str) -> int:
        evidence = self.load()
        remaining = [
            item for item in evidence if item.source.document_id != document_id
        ]
        removed_count = len(evidence) - len(remaining)
        if removed_count:
            self.save(remaining)
        return removed_count
