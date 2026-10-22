"""Where the original bytes of uploads live.

Keys are random and never derived from the user's filename, so a filename
cannot steer where a file is written or collide with another user's. Local
disk for now; an S3-compatible backend only has to implement the same four
methods.
"""

import uuid
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, content: bytes, extension: str) -> str:
        key = f"{uuid.uuid4().hex}{extension}"
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(content)
        temporary.replace(path)
        return key

    def path(self, key: str) -> Path:
        if not key or "/" in key or "\\" in key or key.startswith("."):
            raise ValueError(f"Invalid storage key: {key!r}")
        # Two levels of fan-out keep any one directory small.
        return self._root / key[:2] / key[2:4] / key

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


@lru_cache
def get_storage() -> LocalFileStorage:
    return LocalFileStorage(get_settings().files_dir)
