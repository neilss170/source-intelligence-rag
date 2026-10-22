"""Resolve citation IDs in a reply while it streams.

``resolve_citations`` turns ``[E3]`` into ``[1]`` once the whole reply is
known. A streamed reply arrives in pieces, and a marker can be split across
them (``"[E"`` then ``"3]"``), so this holds back only what might still become
a marker and emits everything else at once. Numbering follows first
appearance, exactly as the batch resolver numbers them; the final, batch
resolved text is still sent when the reply ends and is what gets stored.
"""

from app.services.llm_generator import _CITE_GROUP_RE, _ids_in

#: Spaces dropped before a citation marker, as the batch resolver drops them.
_SPACES = " \t\u00a0\u202f"
_OPEN = "[【"
_CLOSE = "]】"
#: A "[" with no closing bracket this far on is plain text, not a marker.
_MAX_MARKER = 48


class StreamingCitations:
    def __init__(self, ids: dict[str, str]) -> None:
        self._ids = ids
        #: Evidence ID to its number, in order of first citation.
        self.numbers: dict[str, int] = {}
        self._pending = ""
        self._last_marker = ""

    def feed(self, text: str) -> str:
        """Add streamed text; return what can be shown now."""
        self._pending += text
        out: list[str] = []
        while self._pending:
            start = _find_any(self._pending, _OPEN)
            if start < 0:
                # Hold trailing spaces: if a marker follows, they are dropped.
                body = self._pending.rstrip(_SPACES)
                out.append(body)
                self._pending = self._pending[len(body) :]
                if body:
                    self._last_marker = ""
                break
            close = _find_any(self._pending, _CLOSE, start)
            if close < 0:
                if len(self._pending) - start > _MAX_MARKER:
                    out.append(self._pending[: start + 1])
                    self._pending = self._pending[start + 1 :]
                    self._last_marker = ""
                    continue
                before = self._pending[:start]
                kept = before.rstrip(_SPACES)
                out.append(kept)
                if kept:
                    self._last_marker = ""
                self._pending = self._pending[len(kept) :]
                break
            group = self._pending[start : close + 1]
            markers = self._resolve(group)
            before = self._pending[:start]
            if markers is None:
                out.append(before + group)
                self._last_marker = ""
            else:
                kept = before.rstrip(_SPACES)
                if kept:
                    self._last_marker = ""
                out.append(kept)
                for marker in markers:
                    if marker != self._last_marker:
                        out.append(marker)
                        self._last_marker = marker
            self._pending = self._pending[close + 1 :]
        return "".join(out)

    def flush(self) -> str:
        """Whatever is still held when the reply ends."""
        rest, self._pending = self._pending, ""
        return rest

    def _resolve(self, group: str) -> list[str] | None:
        match = _CITE_GROUP_RE.fullmatch(group)
        if not match:
            return None
        markers: list[str] = []
        for cite_id in _ids_in(match.group(1)):
            evidence_id = self._ids.get(cite_id)
            if evidence_id is None:
                continue
            if evidence_id not in self.numbers:
                self.numbers[evidence_id] = len(self.numbers) + 1
            marker = f"[{self.numbers[evidence_id]}]"
            if marker not in markers:
                markers.append(marker)
        return markers


def _find_any(text: str, characters: str, start: int = 0) -> int:
    positions = [i for c in characters if (i := text.find(c, start)) >= 0]
    return min(positions) if positions else -1
