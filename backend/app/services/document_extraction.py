from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pymupdf

from app.services.redaction import redact_contact_details

PDF_SIGNATURE = b"%PDF-"


class DocumentExtractionError(ValueError):
    """Raised when a source document cannot safely be extracted."""


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    filename: str
    content_hash: str
    pages: tuple[ExtractedPage, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


def extract_pdf(
    path: Path,
    *,
    max_size_mb: int = 10,
    redact: bool = True,
    ocr: bool = False,
) -> ExtractedDocument:
    if not path.is_file():
        raise DocumentExtractionError("The PDF does not exist.")
    if path.suffix.lower() != ".pdf":
        raise DocumentExtractionError("Only PDF files are supported by this extractor.")

    content = path.read_bytes()
    if len(content) > max_size_mb * 1024 * 1024:
        raise DocumentExtractionError(
            f"The PDF exceeds the {max_size_mb} MB size limit."
        )
    if not content.startswith(PDF_SIGNATURE):
        raise DocumentExtractionError("The file is not a valid PDF.")

    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except pymupdf.FileDataError as exc:
        raise DocumentExtractionError("The PDF is damaged or unreadable.") from exc

    pages: list[ExtractedPage] = []
    ocr_error: str | None = None
    try:
        for page_index, page in enumerate(document):
            raw_text = page.get_text("text", sort=True)
            if ocr and not raw_text.strip():
                # A scanned page has no text layer. PyMuPDF can OCR it, but
                # only through a locally installed Tesseract.
                try:
                    textpage = page.get_textpage_ocr(full=True)
                    raw_text = page.get_text("text", textpage=textpage, sort=True)
                except Exception as exc:  # noqa: BLE001 - any OCR failure
                    ocr_error = str(exc)
            normalized = _normalize_text(raw_text)
            if normalized:
                pages.append(
                    ExtractedPage(
                        page=page_index + 1,
                        text=redact_contact_details(normalized)
                        if redact
                        else normalized,
                    )
                )
    finally:
        document.close()

    if not pages or sum(len(page.text) for page in pages) < 50:
        if ocr_error:
            raise DocumentExtractionError(
                "The PDF looks scanned and OCR failed. Install Tesseract OCR "
                f"and make sure it is on PATH ({ocr_error})."
            )
        raise DocumentExtractionError(
            "The PDF has no usable text. It may be scanned and require OCR: set "
            "OCR_ENABLED=true and install Tesseract OCR to read it."
        )

    return ExtractedDocument(
        filename=path.name,
        content_hash=sha256(content).hexdigest(),
        pages=tuple(pages),
    )


def _normalize_text(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.replace("\x00", "").splitlines())
    return "\n".join(line for line in lines if line).strip()
