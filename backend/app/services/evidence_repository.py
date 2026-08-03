import json
from pathlib import Path

from pydantic import TypeAdapter

from app.models.resume import EvidenceUnit

EVIDENCE_LIST_ADAPTER = TypeAdapter(list[EvidenceUnit])


class EvidenceRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[EvidenceUnit]:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return EVIDENCE_LIST_ADAPTER.validate_python(payload)
