import json
from pathlib import Path

from pydantic import TypeAdapter

from app.models.evaluation import EvaluationCase

EVAL_SET_ADAPTER = TypeAdapter(list[EvaluationCase])


class EvaluationRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[EvaluationCase]:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return EVAL_SET_ADAPTER.validate_python(payload)
