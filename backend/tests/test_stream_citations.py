import random

import pytest

from app.chat.stream_citations import StreamingCitations
from app.services.llm_generator import clean_untrusted, resolve_citations

IDS = {"E1": "ev_a", "E2": "ev_b", "E3": "ev_c"}

REPLIES = [
    "The fleet has 214 trucks [E1]. Both agree [E1][E2] and [E3, E1].",
    "Range [E1-E3] then an unknown [E9] and plain [brackets] here.",
    "An unclosed [ bracket that never closes and goes on for quite a long while",
    "【E2】 full-width, spaced [ E1 ], repeated [E2] [E2].",
    "Tabs\t[E1]\tand a newline\n[E2] end",
    # Models put no-break spaces before markers; they must be dropped too.
    "Total €174,254.56 [E1]. Spaced [E2].",
    "No citations at all.",
]


@pytest.mark.parametrize("reply", REPLIES)
def test_streaming_matches_batch_resolution_however_it_is_chunked(reply) -> None:
    expected, cited = resolve_citations(reply, IDS)
    rng = random.Random(reply)

    for trial in range(200):
        resolver = StreamingCitations(IDS)
        shown, position = "", 0
        while position < len(reply):
            size = 1 if trial == 0 else rng.randint(1, 7)
            shown += resolver.feed(reply[position : position + size])
            position += size
        shown += resolver.flush()

        assert shown.strip() == expected
        assert list(resolver.numbers) == cited


def test_hidden_characters_are_removed_from_untrusted_text() -> None:
    hidden = "a​b‮c⁦d﻿e\x07f"

    assert clean_untrusted(hidden) == "abcdef"
    assert clean_untrusted("line one\n\tline two") == "line one\n\tline two"
