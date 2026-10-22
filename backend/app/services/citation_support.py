"""Check that each cited claim is actually supported by the passage it cites.

Citation IDs are validated against what was retrieved, which proves the model
was *shown* a passage - not that the passage says what the sentence claims.
This closes that gap with a natural-language-inference model: every sentence
carrying a ``[n]`` marker is checked against sentences from the passages it
cites, and is supported when at least one of them entails it.

The result is the answer's real groundedness score - the share of cited
sentences that are supported - and the list of sentences that are not, which
the interface shows as a warning rather than silently deleting them: a
paraphrase the NLI model is unsure of is better flagged than lost.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

_MARKER = re.compile(r"\[(\d+)\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")

#: Sentences this short ("Yes[1].") carry no claim the model can check.
MIN_CLAIM_CHARS = 12

#: Sentence runs checked per claim (each with and without its section path).
MAX_WINDOWS = 5

_PASSAGE_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_NO_BREAK_SPACE = re.compile(r"[    ]")
_NO_BREAK_HYPHEN = re.compile(r"[‐‑]")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SupportReport:
    score: float
    checked: int
    unsupported: list[str] = field(default_factory=list)


@lru_cache
def load_nli(model_name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


class SupportVerifier:
    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-xsmall",
        *,
        threshold: float = 0.5,
        model=None,
    ) -> None:
        self._model = model or load_nli(model_name)
        labels = getattr(getattr(self._model, "config", None), "id2label", None) or {}
        self._entailment = next(
            (int(i) for i, label in labels.items() if label.lower() == "entailment"),
            1,
        )
        self._threshold = threshold

    def verify(
        self,
        answer: str,
        passages: dict[int, str],
        contexts: dict[int, str] | None = None,
    ) -> SupportReport:
        """Check every cited sentence in ``answer`` against ``passages`` by number.

        Args:
            contexts: Where each passage sits, such as its section path. It is
                put in front of every sentence taken from that passage, so
                "the CTO, Amara Okafor" still supports "Amara Okafor is
                Northwind's CTO" when only the heading names Northwind.
        """
        contexts = contexts or {}
        claims: list[tuple[str, list[int]]] = []
        for sentence in _SENTENCE.split(answer):
            numbers = [int(n) for n in _MARKER.findall(sentence)]
            claim = _plain(_MARKER.sub("", sentence)).strip(" -*•\t")
            checkable = [n for n in numbers if n in passages]
            # A claim citing only passages left out of ``passages`` - table
            # rows and SQL results, which NLI models cannot read - is skipped.
            if checkable and len(claim) >= MIN_CLAIM_CHARS:
                claims.append((claim, checkable))
        if not claims:
            return SupportReport(score=0.0, checked=0)

        premises = [
            _windows(claim, [(contexts.get(n, ""), passages[n]) for n in numbers])
            for claim, numbers in claims
        ]
        pairs = [
            (premise, claim)
            for (claim, _), options in zip(claims, premises, strict=True)
            for premise in options
        ]
        probabilities = self._model.predict(pairs, apply_softmax=True) if pairs else []
        entailed = iter(float(row[self._entailment]) for row in probabilities)
        unsupported = []
        for (claim, _), options in zip(claims, premises, strict=True):
            best = max((next(entailed) for _ in options), default=0.0)
            if best < self._threshold:
                unsupported.append(claim)
        supported = len(claims) - len(unsupported)
        return SupportReport(
            score=round(supported / len(claims), 3),
            checked=len(claims),
            unsupported=unsupported,
        )


def _plain(text: str) -> str:
    """``text`` with typographic spacing undone.

    Models write narrow no-break spaces ("45\\u202fEUR") and no-break hyphens,
    which NLI tokenizers do not read as spaces and hyphens - a claim written
    that way scores as unsupported however true it is.
    """
    text = _NO_BREAK_SPACE.sub(" ", text)
    text = _NO_BREAK_HYPHEN.sub("-", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return " ".join(text.split())


def _windows(claim: str, passages: list[tuple[str, str]]) -> list[str]:
    """The sentence windows of ``passages`` most likely to support ``claim``.

    Small NLI models judge a whole passage as "neutral" towards a claim one
    of its sentences states outright, so premises are runs of one to three
    consecutive sentences - the longer runs catch a claim that joins facts
    from neighbouring sentences. Only the ``MAX_WINDOWS`` runs sharing the
    most words with the claim are kept, which bounds the cost.

    Each run is checked twice: with its section path in front, which lets
    "the CTO, Amara Okafor" support "Amara Okafor is Northwind's CTO", and
    without, because the prefix can also distract the model from a plain
    match. Tuned on the document evaluation set: this leaves only claims that
    need arithmetic flagged, which NLI cannot check.
    """
    words = set(_WORD.findall(claim.lower()))
    candidates: list[tuple[str, str]] = []
    for context, passage in passages:
        sentences = [s for s in _PASSAGE_SENTENCE.split(passage) if s.strip()]
        candidates.extend(
            (context, " ".join(sentences[i : i + size]))
            for size in (1, 2, 3)
            for i in range(len(sentences) - size + 1)
        )
    ranked = sorted(
        candidates, key=lambda c: -len(words & set(_WORD.findall(c[1].lower())))
    )[:MAX_WINDOWS]
    windows: list[str] = []
    for context, span in ranked:
        if context:
            windows.append(f"{context}: {span}")
        windows.append(span)
    return windows
