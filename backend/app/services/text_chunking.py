import re

from app.services.document_extraction import ExtractedPage

PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def chunk_pages(
    pages: list[ExtractedPage] | tuple[ExtractedPage, ...],
    *,
    max_characters: int = 1200,
) -> list[tuple[int, str]]:
    chunks: list[tuple[int, str]] = []
    for page in pages:
        paragraphs = [
            " ".join(paragraph.split())
            for paragraph in PARAGRAPH_BREAK.split(page.text)
            if paragraph.strip()
        ]
        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > max_characters:
                if current:
                    chunks.append((page.page, current))
                    current = ""
                chunks.extend(
                    (page.page, paragraph[index : index + max_characters].strip())
                    for index in range(0, len(paragraph), max_characters)
                )
            elif not current:
                current = paragraph
            elif len(current) + len(paragraph) + 2 <= max_characters:
                current = f"{current}\n\n{paragraph}"
            else:
                chunks.append((page.page, current))
                current = paragraph
        if current:
            chunks.append((page.page, current))
    return chunks
