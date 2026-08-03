from app.services.web_search import _compact, needs_live_search


def test_detects_general_live_information_requests() -> None:
    assert needs_live_search("Find current laptop prices and links") is True
    assert needs_live_search("What restaurants are near me?") is True
    assert needs_live_search("Explain how a binary tree works") is False


def test_compacts_search_content_to_reduce_tokens() -> None:
    compacted = _compact("word " * 100, 80)

    assert len(compacted) <= 80
    assert compacted.endswith("...")
