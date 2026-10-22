from app.services.document_extraction import ExtractedPage
from app.services.text_chunking import chunk_pages


def _sentences(count: int, start: int = 0) -> str:
    return " ".join(
        f"Sentence number {i} explains one specific fact about the warehouse."
        for i in range(start, start + count)
    )


def test_long_paragraph_is_split_between_sentences_with_overlap() -> None:
    chunks = chunk_pages([ExtractedPage(1, _sentences(60))], max_characters=600)

    assert len(chunks) > 1
    assert all(chunk.text.endswith(".") for chunk in chunks)
    for previous, following in zip(chunks, chunks[1:], strict=False):
        last_sentence = previous.text.rsplit(". ", 1)[-1]
        assert following.text.startswith(last_sentence.rstrip("."))


def test_markdown_headings_become_section_paths_not_chunks() -> None:
    text = (
        "# Report\n\n## Safety\n\nIncidents fell to 7.\n\n"
        "## Fleet\n\nWe added 38 vans.\n\n### Fuel\n\nDiesel fell 11%."
    )
    chunks = chunk_pages([ExtractedPage(1, text)])

    assert [(c.heading, c.text) for c in chunks] == [
        ("Report > Safety", "Incidents fell to 7."),
        ("Report > Fleet", "We added 38 vans."),
        ("Report > Fleet > Fuel", "Diesel fell 11%."),
    ]


def test_plain_text_title_lines_are_headings() -> None:
    text = (
        "Meals and allowance\n\nThe daily allowance is 45 EUR.\n\n"
        "Hotels\n\nCap 160 EUR."
    )
    chunks = chunk_pages([ExtractedPage(1, text)])

    assert [c.heading for c in chunks] == ["Meals and allowance", "Hotels"]


def test_table_rows_are_never_split() -> None:
    rows = "\n".join(
        f"Row {i}: name: Item {i} | price: {i * 10} | stock: {i}" for i in range(80)
    )
    chunks = chunk_pages(
        [ExtractedPage(1, f"## Worksheet: Stock\n\n{rows}")], max_characters=500
    )

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.heading == "Worksheet: Stock"
        assert all(line.startswith("Row ") for line in chunk.text.splitlines())


def test_pdf_paragraph_continues_across_pages_when_merged() -> None:
    pages = [
        ExtractedPage(1, "The migration was delayed because mapping"),
        ExtractedPage(2, "the data took longer than expected."),
    ]

    merged = chunk_pages(pages, merge_pages=True)
    separate = chunk_pages(pages)

    assert len(merged) == 1
    assert merged[0].page == 1
    assert "mapping the data" in merged[0].text
    assert len(separate) == 2


def test_overlong_sentence_is_split_on_words() -> None:
    chunks = chunk_pages([ExtractedPage(1, "word " * 400)], max_characters=300)

    assert all(len(chunk.text) <= 300 for chunk in chunks)
    assert all(not chunk.text.endswith("wor") for chunk in chunks)
