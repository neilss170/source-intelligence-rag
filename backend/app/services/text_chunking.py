"""Split extracted pages into passages that are worth retrieving and citing.

Three rules, each fixing a way the old character slicer lost answers:

**Cut between sentences, never inside one.** Prose is split into sentences
and packed up to ``max_characters``; the last sentence of a passage is
repeated at the start of the next, so a fact that spans the boundary is whole
in at least one of them. A single sentence longer than the limit is the only
thing split mid-text, and then on a word boundary.

**Cut between rows, never inside one.** Tables flattened to one record per
line (spreadsheets, Word tables) are packed line by line, so a row is never
split across two passages.

**Every passage knows its section.** Markdown headings - and the short title
lines plain text and PDFs use instead - are tracked as a path such as
``Report > Safety``. A heading is never a passage by itself; it travels with
the text under it as the passage's ``heading``.
"""

import re
from dataclasses import dataclass

from app.services.document_extraction import ExtractedPage

PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])")
#: A line that is a record rather than wrapped prose: "Row 4: ...",
#: "price: 4999", "Warranty | Two years".
RECORD_LINE = re.compile(r"^(?:Row \d+:|[^\s:][^:]{0,60}:\s|.*\s\|\s)")

#: Plain-text title lines: short, capitalised, no closing punctuation.
PLAIN_HEADING_MAX = 120
PLAIN_HEADING_LEVEL = 2

#: Sentences longer than this are not repeated as overlap.
OVERLAP_MAX = 300


@dataclass(frozen=True, slots=True)
class Chunk:
    page: int
    text: str
    #: Section path, e.g. "Annual report > Safety". Empty before any heading.
    heading: str = ""


@dataclass(frozen=True, slots=True)
class _Unit:
    page: int
    text: str
    #: "prose" or "row" - rows are never repeated as overlap.
    kind: str
    #: First unit of a paragraph or table, so the passage keeps the break.
    opens_block: bool


def chunk_pages(
    pages: list[ExtractedPage] | tuple[ExtractedPage, ...],
    *,
    max_characters: int = 1200,
    merge_pages: bool = False,
) -> list[Chunk]:
    """Passages for ``pages``, in reading order.

    Args:
        max_characters: Upper bound on a passage's length.
        merge_pages: Let a passage run across a page break, as a paragraph in
            a PDF does. The passage is cited by the page it starts on. Off
            for one-record-per-page sources such as CSV rows.
    """
    chunks: list[Chunk] = []
    headings: list[tuple[int, str]] = []
    section: list[_Unit] = []

    def flush() -> None:
        path = " > ".join(title for _, title in headings)
        chunks.extend(_pack(section, path, max_characters))
        section.clear()

    blocks = [
        (page.page, [line.strip() for line in block.splitlines() if line.strip()])
        for page in pages
        for block in PARAGRAPH_BREAK.split(page.text)
    ]
    blocks = [(page, lines) for page, lines in blocks if lines]
    current_page: int | None = None
    for index, (page_number, lines) in enumerate(blocks):
        if not merge_pages and page_number != current_page:
            flush()
        current_page = page_number
        following = blocks[index + 1][1][0] if index + 1 < len(blocks) else ""
        if (
            section
            and lines[0][:1].islower()
            and section[-1].kind == "prose"
            and not section[-1].text.endswith((".", "!", "?", ":"))
        ):
            # The sentence before a page break carries on here: rejoin it.
            tail = section.pop()
            lines = [tail.text, *lines]
            page_number = tail.page
        body: list[str] = []
        for line in lines:
            heading = MARKDOWN_HEADING.match(line)
            if heading:
                section.extend(_units(body, page_number))
                body = []
                flush()
                level = len(heading.group(1))
                headings[:] = [h for h in headings if h[0] < level]
                headings.append((level, heading.group(2).strip()))
            else:
                body.append(line)
        # A title line has text after it, and that text does not carry on in
        # lower case - which would make it a sentence broken by a page or
        # column break, not a heading.
        if (
            len(body) == 1
            and _is_plain_heading(body[0])
            and following
            and not following[0].islower()
        ):
            flush()
            headings[:] = [h for h in headings if h[0] < PLAIN_HEADING_LEVEL]
            headings.append((PLAIN_HEADING_LEVEL, body[0]))
            continue
        section.extend(_units(body, page_number))
    flush()
    return chunks


def _is_plain_heading(line: str) -> bool:
    return (
        len(line) <= PLAIN_HEADING_MAX
        and line[:1].isupper()
        and not line.endswith((".", ",", ";", ":", "!", "?"))
        and not RECORD_LINE.match(line)
        and len(line.split()) <= 16
    )


def _units(lines: list[str], page: int) -> list[_Unit]:
    if not lines:
        return []
    records = sum(1 for line in lines if RECORD_LINE.match(line))
    if len(lines) > 1 and records * 5 >= len(lines) * 3:
        return [
            _Unit(page, line, "row", index == 0) for index, line in enumerate(lines)
        ]
    sentences = SENTENCE_END.split(" ".join(lines))
    return [
        _Unit(page, sentence.strip(), "prose", index == 0)
        for index, sentence in enumerate(sentences)
        if sentence.strip()
    ]


def _pack(units: list[_Unit], heading: str, max_characters: int) -> list[Chunk]:
    pieces: list[_Unit] = []
    for unit in units:
        if len(unit.text) <= max_characters:
            pieces.append(unit)
            continue
        for index, part in enumerate(_split_words(unit.text, max_characters)):
            pieces.append(
                _Unit(unit.page, part, "long", unit.opens_block and index == 0)
            )

    chunks: list[Chunk] = []
    current: list[_Unit] = []
    size = 0
    for unit in pieces:
        added = len(unit.text) + 2
        if current and size + added > max_characters:
            chunks.append(_join(current, heading))
            tail = current[-1]
            carry = (
                tail.kind == "prose"
                and len(tail.text) <= OVERLAP_MAX
                and len(tail.text) + added <= max_characters
            )
            current = [_Unit(tail.page, tail.text, tail.kind, True)] if carry else []
            size = len(tail.text) + 2 if carry else 0
        current.append(unit)
        size += added
    if current:
        chunks.append(_join(current, heading))
    return chunks


def _join(units: list[_Unit], heading: str) -> Chunk:
    text = units[0].text
    for unit in units[1:]:
        separator = "\n\n" if unit.opens_block else "\n" if unit.kind == "row" else " "
        text += separator + unit.text
    return Chunk(page=units[0].page, text=text, heading=heading)


def _split_words(text: str, max_characters: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > max_characters:
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:max_characters])
            word = word[max_characters:]
        if current and len(current) + 1 + len(word) > max_characters:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        parts.append(current)
    return parts
