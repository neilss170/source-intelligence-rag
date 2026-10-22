"""Decide what an upload really is, from its bytes rather than its name."""

import io
import zipfile
from pathlib import Path

from app.core.errors import AppError

TEXT_KINDS = {".txt", ".md", ".markdown", ".csv", ".json"}
SUPPORTED_KINDS = TEXT_KINDS | {".pdf", ".docx", ".xlsx"}

#: What an Office file's [Content_Types].xml must mention for its kind.
_OFFICE_MARKERS = {
    ".docx": b"wordprocessingml.document.main",
    ".xlsx": b"spreadsheetml.sheet.main",
}


def unsupported(filename: str) -> AppError:
    return AppError(
        415,
        "unsupported_type",
        f"{filename} isn't a supported file. Upload PDF, DOCX, TXT, Markdown, "
        "CSV, JSON or XLSX.",
    )


def detect_kind(filename: str, content: bytes) -> str:
    """The upload's kind (".pdf", ".docx", ...), checked against its content.

    The extension says what the file claims to be; the bytes must agree. A
    renamed executable, an archive posing as a Word file, or binary data
    named .txt is refused.
    """
    kind = Path(filename).suffix.lower()
    if kind not in SUPPORTED_KINDS:
        raise unsupported(filename)
    if kind == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise unsupported(filename)
    elif kind in _OFFICE_MARKERS:
        if not content.startswith(b"PK\x03\x04"):
            raise unsupported(filename)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                manifest = archive.read("[Content_Types].xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise unsupported(filename) from exc
        if _OFFICE_MARKERS[kind] not in manifest:
            raise unsupported(filename)
    else:
        if b"\x00" in content[:8192]:
            raise unsupported(filename)
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppError(
                415,
                "unsupported_encoding",
                f"{filename} isn't UTF-8 text. Save it as UTF-8 and upload it again.",
            ) from exc
    return kind
