"""One chat turn, from question to stored answer, as a stream of events.

``ChatService.run`` yields server-sent events:

``status``        what is happening ("Searching your documents")
``token``         answer text as it is written
``citations``     the sources behind the answer, numbered as in the text
``web_sources``   links, for answers from live web search
``verification``  the claim check: groundedness and unsupported sentences
``done``          the stored message: id, final text, mode, model, usage, timings
``error``         a stable ``code`` and a readable ``message``

The prompt, citation rules and abstention are the measured ones
(``AnswerPrompt``); this module adds streaming, persistence, budgets and the
choice between documents, general chat and the web.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.providers import AllModelsExhausted, ModelRouter, ProviderError, Usage
from app.chat.stream_citations import StreamingCitations
from app.chat.usage import record_usage, tokens_used_today
from app.core.config import Settings
from app.db import repository
from app.db.models import Chat, Message
from app.models.query import ChatMessage, ChatRole
from app.retrieval.pg import (
    FileSummary,
    workspace_files,
    workspace_passages,
    workspace_retriever,
    workspace_size,
    workspace_tables,
)
from app.services.bm25_retriever import ScoredEvidence
from app.services.citation_support import SupportVerifier
from app.services.general_knowledge import general_system
from app.services.llm_generator import (
    _REWRITE_SYSTEM,
    INSUFFICIENT_CONTEXT,
    MAX_SQL_ROUNDS,
    AnswerPrompt,
    _best_first,
    _duration,
    _replay,
    _sql_request,
    _wants_document_order,
    overview_of_files,
)
from app.services.query_service import _is_prose
from app.services.web_search import needs_live_search

logger = logging.getLogger(__name__)

Scope = Literal["auto", "workspace", "general"]

#: Messages replayed as conversation history (four exchanges).
HISTORY_MESSAGES = 8
EMPTY_WORKSPACE = (
    "There are no documents in this workspace yet. Upload a PDF, DOCX, TXT, "
    "Markdown, CSV, JSON or Excel file, then ask about it."
)
#: Characters of a reply held back before deciding it is safe to stream:
#: enough to tell "SQL:" or "INSUFFICIENT_CONTEXT" from a real answer.
_DECIDE_AFTER = 24
_HELD_PREFIXES = ("SQL:", "```", INSUFFICIENT_CONTEXT)


@dataclass(frozen=True)
class Turn:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    chat_id: uuid.UUID
    question: str
    scope: Scope = "auto"


@dataclass
class _Outcome:
    """What a turn produced, for storage."""

    content: str = ""
    mode: str = "general"
    citations: list[dict] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    groundedness: float | None = None
    model: str = ""
    calls: list[tuple[str, Usage]] = field(default_factory=list)
    timings: dict[str, int] = field(default_factory=dict)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        sessions: Callable[[], Session],
        router: ModelRouter | None,
        ranker,
        verifier: SupportVerifier | None = None,
        web=None,
        retriever_factory=workspace_retriever,
    ) -> None:
        """Create the service.

        Args:
            ranker: Anything with ``score(query, evidence) -> list[float]``,
                for ordering a workspace that is sent whole.
            web: A web search provider (``configured``, ``search``), or None.
        """
        self._settings = settings
        self._sessions = sessions
        self._router = router
        self._ranker = ranker
        self._verifier = verifier
        self._web = web
        self._retriever_factory = retriever_factory

    async def run(self, turn: Turn) -> AsyncIterator[str]:
        started = perf_counter()
        outcome = _Outcome()
        try:
            begun = await asyncio.to_thread(self._begin, turn)
        except Exception:
            logger.exception("Could not start chat turn")
            yield sse("error", {"code": "internal_error", "message": _SORRY})
            return
        history, files, used = begun

        budget = self._settings.daily_token_budget_per_user
        if budget and used >= budget:
            yield sse(
                "error",
                {
                    "code": "daily_budget_reached",
                    "message": "You've used today's question allowance. It resets "
                    "at midnight UTC.",
                },
            )
            return
        if self._router is None:
            yield sse(
                "error",
                {
                    "code": "no_model",
                    "message": "No language model is configured. Set CHAT_API_KEY.",
                },
            )
            return

        try:
            async for event in self._answer(turn, history, files, outcome):
                yield event
        except AllModelsExhausted as exc:
            yield sse(
                "error",
                {
                    "code": "model_quota",
                    "message": "The language model's usage limit has been reached. "
                    f"Try again in about {_duration(exc.retry_after)}.",
                },
            )
            await asyncio.to_thread(self._record_calls, turn, outcome)
            return
        except Exception:
            logger.exception("Chat turn failed")
            yield sse("error", {"code": "internal_error", "message": _SORRY})
            await asyncio.to_thread(self._record_calls, turn, outcome)
            return

        outcome.timings["total_ms"] = _ms(started)
        message_id = await asyncio.to_thread(self._finish, turn, outcome)
        yield sse(
            "done",
            {
                "message_id": str(message_id),
                "content": outcome.content,
                "mode": outcome.mode,
                "model": outcome.model,
                "groundedness": outcome.groundedness,
                "usage": _usage_totals(outcome.calls),
                "latency": outcome.timings,
            },
        )

    # -- the paths a question can take ----------------------------------------

    async def _answer(self, turn, history, files, outcome) -> AsyncIterator[str]:
        replay = _replay(history)
        question = turn.question
        ready = [f for f in files if f.status == "ready"]
        indexing = [f for f in files if f.status in ("uploaded", "indexing")]

        if turn.scope != "general" and not ready and indexing:
            # Answering as general chat here reads as "your file says nothing
            # about that". Say the file isn't ready yet instead.
            names = ", ".join(f.filename for f in indexing[:3])
            outcome.content = (
                f"{names} {'is' if len(indexing) == 1 else 'are'} still being "
                "indexed. Ask again in a moment and I'll answer from "
                f"{'it' if len(indexing) == 1 else 'them'}."
            )
            outcome.mode = "indexing"
            yield sse("token", {"text": outcome.content})
            return
        if turn.scope == "workspace" and not ready:
            outcome.content, outcome.mode = EMPTY_WORKSPACE, "empty_workspace"
            yield sse("token", {"text": EMPTY_WORKSPACE})
            return
        if turn.scope == "general" or not ready:
            async for event in self._general(turn, replay, outcome):
                yield event
            return

        if replay:
            yield sse("status", {"text": "Understanding your follow-up"})
            question = await self._rewrite(question, replay, outcome)

        yield sse("status", {"text": "Searching your documents"})
        started = perf_counter()
        hits, whole, tables = await asyncio.to_thread(self._retrieve, turn, question)
        outcome.timings["retrieve_ms"] = _ms(started)

        prompt = AnswerPrompt.build(
            question,
            hits,
            overview=overview_of_files(files),
            tables=tables,
            whole_workspace=whole,
            history=replay,
            model=await self._router.current_model(),
        )
        started = perf_counter()
        try:
            raw, streamed = None, False
            async for item in self._generate(prompt, tables, outcome):
                if isinstance(item, tuple):
                    raw, streamed = item
                else:
                    yield item
        except ProviderError as exc:
            if exc.status != 413 or len(hits) <= 3:
                raise
            # Over the provider's request size: the best half of the
            # passages usually still holds the answer.
            prompt = AnswerPrompt.build(
                question,
                _best_first(hits)[: max(2, len(hits) // 2)],
                overview=overview_of_files(files),
                tables=tables,
                whole_workspace=False,
                history=replay,
                model=await self._router.current_model(),
            )
            async for item in self._generate(prompt, tables, outcome):
                if isinstance(item, tuple):
                    raw, streamed = item
                else:
                    yield item
        outcome.timings["generate_ms"] = _ms(started)

        generated = prompt.interpret(raw or "")
        if not streamed:
            yield sse("token", {"text": generated.answer})
        outcome.content = generated.answer

        if generated.abstained:
            outcome.mode = "workspace"
            return
        if not generated.evidence_ids:
            # The model answered without the documents: small talk, a
            # question about the assistant, or general knowledge.
            if self._web_wanted(turn):
                async for event in self._from_web(turn, outcome):
                    yield event
                return
            outcome.mode = "general"
            return

        outcome.mode = "workspace"
        by_id = {hit.evidence.evidence_id: hit for hit in hits}
        by_id.update(
            {e.evidence_id: ScoredEvidence(e, 1.0) for e in generated.extra_evidence}
        )
        cited = [by_id[evidence_id] for evidence_id in generated.evidence_ids]
        outcome.citations = [
            {
                "number": number,
                "evidence_id": hit.evidence.evidence_id,
                "title": hit.evidence.title,
                "filename": hit.evidence.source.filename,
                "page": hit.evidence.source.page,
                "excerpt": hit.evidence.source.source_text,
                "relevance": max(0.0, min(1.0, float(hit.score))),
            }
            for number, hit in enumerate(cited, start=1)
        ]
        yield sse("citations", {"citations": outcome.citations})

        if self._verifier is not None:
            started = perf_counter()
            prose = {
                n: hit.evidence
                for n, hit in enumerate(cited, start=1)
                if _is_prose(hit.evidence)
            }
            report = await asyncio.to_thread(
                self._verifier.verify,
                generated.answer,
                {n: e.text for n, e in prose.items()},
                {n: e.title.split(" > ", 1)[-1] for n, e in prose.items()},
            )
            outcome.timings["verify_ms"] = _ms(started)
            outcome.groundedness = report.score if report.checked else 1.0
            outcome.unsupported = report.unsupported
            yield sse(
                "verification",
                {
                    "groundedness": outcome.groundedness,
                    "unsupported_claims": outcome.unsupported,
                },
            )

    async def _generate(self, prompt: AnswerPrompt, tables, outcome):
        """Stream the reply; yields events, then ``(raw_reply, streamed)``.

        The first characters are held until it is clear the reply is an
        answer and not a SQL request or an abstention, which are never shown.
        """
        for round_number in range(MAX_SQL_ROUNDS + 1):
            parts: list[str] = []
            citations = StreamingCitations(prompt.ids)
            state = "deciding"
            async for delta in self._router.stream(prompt.system, prompt.user):
                if delta.usage is not None:
                    outcome.calls.append((delta.model, delta.usage))
                    outcome.model = delta.model
                if not delta.text:
                    continue
                parts.append(delta.text)
                if state == "deciding":
                    state = _classify("".join(parts))
                    if state == "stream":
                        text = citations.feed("".join(parts))
                        if text:
                            yield sse("token", {"text": text})
                elif state == "stream":
                    text = citations.feed(delta.text)
                    if text:
                        yield sse("token", {"text": text})
            raw = "".join(parts)
            if state == "deciding":
                state = "hold" if _classify(raw, final=True) == "hold" else "late"
            sql = _sql_request(raw)
            if sql is not None and tables and round_number < MAX_SQL_ROUNDS:
                yield sse("status", {"text": "Running a query on your spreadsheet"})
                await asyncio.to_thread(prompt.add_query, sql, tables)
                continue
            if sql is not None:
                raw = INSUFFICIENT_CONTEXT
            if state == "stream":
                tail = citations.flush()
                if tail:
                    yield sse("token", {"text": tail})
            yield (raw, state == "stream")
            return

    async def _general(self, turn: Turn, replay: str, outcome) -> AsyncIterator[str]:
        if self._web_wanted(turn):
            async for event in self._from_web(turn, outcome):
                yield event
            return
        user = turn.question
        if replay:
            user = f"--- EARLIER IN THIS CONVERSATION ---\n{replay}\n\n{turn.question}"
        model = await self._router.current_model()
        started = perf_counter()
        parts: list[str] = []
        async for delta in self._router.stream(general_system(model), user):
            if delta.usage is not None:
                outcome.calls.append((delta.model, delta.usage))
                outcome.model = delta.model
            if delta.text:
                parts.append(delta.text)
                yield sse("token", {"text": delta.text})
        outcome.timings["generate_ms"] = _ms(started)
        outcome.content, outcome.mode = "".join(parts).strip(), "general"

    def _web_wanted(self, turn: Turn) -> bool:
        return (
            turn.scope == "auto"
            and self._web is not None
            and getattr(self._web, "configured", False)
            and needs_live_search(turn.question)
        )

    async def _from_web(self, turn: Turn, outcome) -> AsyncIterator[str]:
        yield sse("status", {"text": "Searching the web"})
        result = await asyncio.to_thread(self._web.search, turn.question)
        if result is None:
            outcome.content = "I couldn't get live web results just now."
            outcome.mode = "general"
            yield sse("token", {"text": outcome.content})
            return
        outcome.content, outcome.mode = result.answer, "general"
        yield sse("token", {"text": result.answer})
        yield sse(
            "web_sources",
            {"sources": [source.model_dump() for source in result.sources]},
        )

    async def _rewrite(self, question: str, replay: str, outcome) -> str:
        started = perf_counter()
        try:
            completion = await self._router.complete(
                _REWRITE_SYSTEM,
                f"--- EARLIER CONVERSATION ---\n{replay}\n\n"
                f"--- FOLLOW-UP QUESTION ---\n{question}",
                max_tokens=1024,
            )
        except (ProviderError, AllModelsExhausted) as exc:
            logger.warning("Searching the question as typed; rewrite failed: %s", exc)
            return question
        finally:
            outcome.timings["rewrite_ms"] = _ms(started)
        outcome.calls.append((completion.model, completion.usage))
        rewritten = " ".join(completion.text.strip().strip("\"'").split())
        return rewritten if 2 <= len(rewritten) <= 1000 else question

    # -- database work (runs in threads) ---------------------------------------

    def _begin(self, turn: Turn) -> tuple[list[ChatMessage], list[FileSummary], int]:
        with self._sessions() as db:
            chat = repository.get_chat(db, turn.workspace_id, turn.chat_id)
            earlier = list(
                db.scalars(
                    select(Message)
                    .where(Message.chat_id == chat.id)
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(HISTORY_MESSAGES)
                )
            )
            history = [
                ChatMessage(
                    role=ChatRole.USER if m.role == "user" else ChatRole.ASSISTANT,
                    content=m.content[:4000],
                )
                for m in reversed(earlier)
                if m.content.strip()
            ]
            db.add(Message(chat_id=chat.id, role="user", content=turn.question))
            chat.updated_at = datetime.now(UTC)
            if chat.title == "New chat":
                chat.title = turn.question.strip()[:60] or chat.title
            db.commit()
            files = workspace_files(db, turn.workspace_id)
            used = tokens_used_today(db, turn.user_id)
        return history, files, used

    def _retrieve(self, turn: Turn, question: str):
        with self._sessions() as db:
            size = workspace_size(db, turn.workspace_id)
            if size <= self._settings.workspace_context_chars:
                passages = workspace_passages(db, turn.workspace_id)
                if _wants_document_order(question):
                    hits = [ScoredEvidence(p, 1.0) for p in passages]
                else:
                    scores = self._ranker.score(question, passages)
                    hits = [
                        ScoredEvidence(p, s)
                        for p, s in sorted(
                            zip(passages, scores, strict=True), key=lambda x: -x[1]
                        )
                    ]
                whole = True
            else:
                retriever = self._retriever_factory(
                    db, turn.workspace_id, self._settings
                )
                hits = retriever.search(question, top_k=self._settings.retrieval_top_k)
                whole = False
            tables = (
                workspace_tables(db, turn.workspace_id)
                if self._settings.table_queries_enabled
                else None
            )
        return hits, whole, (tables if tables else None)

    def _finish(self, turn: Turn, outcome: _Outcome) -> uuid.UUID:
        with self._sessions() as db:
            message = Message(
                chat_id=turn.chat_id,
                role="assistant",
                content=outcome.content,
                citations=outcome.citations,
                unsupported_claims=outcome.unsupported,
                mode=outcome.mode,
                model=outcome.model or None,
                groundedness=outcome.groundedness,
                usage=_usage_totals(outcome.calls),
                latency=outcome.timings,
            )
            db.add(message)
            chat = db.get(Chat, turn.chat_id)
            if chat is not None:
                chat.updated_at = datetime.now(UTC)
            self._add_usage(db, turn, outcome)
            db.commit()
            return message.id

    def _record_calls(self, turn: Turn, outcome: _Outcome) -> None:
        with self._sessions() as db:
            self._add_usage(db, turn, outcome)
            db.commit()

    @staticmethod
    def _add_usage(db: Session, turn: Turn, outcome: _Outcome) -> None:
        for model, usage in outcome.calls:
            record_usage(db, turn.user_id, model, usage.tokens_in, usage.tokens_out)


_SORRY = "Something went wrong while answering. Try again in a moment."


def _classify(head: str, *, final: bool = False) -> str:
    """'hold' for a SQL request or abstention, 'stream' for an answer, or
    'deciding' while the first characters could still be either."""
    text = head.lstrip()
    words = text.lstrip("*_ \t\n").upper()
    if any(words.startswith(p) or text.startswith(p) for p in _HELD_PREFIXES):
        return "hold"
    could_be = any(
        p.startswith(words[: len(p)]) or p.startswith(text[: len(p)])
        for p in _HELD_PREFIXES
    )
    if could_be and len(text) < _DECIDE_AFTER and not final:
        return "deciding"
    return "stream"


def _usage_totals(calls: list[tuple[str, Usage]]) -> dict:
    return {
        "calls": len(calls),
        "tokens_in": sum(u.tokens_in for _, u in calls),
        "tokens_out": sum(u.tokens_out for _, u in calls),
    }


def _ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
