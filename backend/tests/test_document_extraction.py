from pathlib import Path

import pymupdf
import pytest

from app.services.document_extraction import DocumentExtractionError, extract_pdf


def _write_pdf(path: Path, text: str) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_extracts_page_text_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "resume.pdf"
    _write_pdf(
        path,
        "Sample Candidate candidate@example.com Python FastAPI project experience",
    )

    result = extract_pdf(path)

    assert result.pages[0].page == 1
    assert "Python FastAPI" in result.text
    assert "candidate@example.com" not in result.text
    assert len(result.content_hash) == 64


def test_rejects_empty_or_scanned_pdf(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    with pytest.raises(DocumentExtractionError, match="require OCR"):
        extract_pdf(path)


def test_rejects_fake_pdf(tmp_path: Path) -> None:
    path = tmp_path / "fake.pdf"
    path.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(DocumentExtractionError, match="not a valid PDF"):
        extract_pdf(path)
