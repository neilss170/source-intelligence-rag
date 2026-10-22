"""Streaming access to language models, with a fallback chain.

Two wire formats cover the providers that matter: the OpenAI chat format
(OpenAI, Groq, OpenRouter, Ollama, vLLM) and Anthropic's Messages API. Each
model in the chain has its own endpoint and key, so a hosted model and a
local Ollama model can back each other up.

**Quota handling (measured):** free tiers meter tokens per model per minute
and per day. A rate limit that clears within ``MAX_RETRY_WAIT_S`` is waited
out once. A longer one marks the model exhausted until it resets - in Redis,
so every worker skips it - and the same request moves to the next model.
Only when every model is exhausted does the caller get
``AllModelsExhausted``, with how long until the first one is back.

A failure after the first token has streamed is not retried on another
model: half an answer from one model and half from another is worse than an
error.
"""

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

MAX_RETRY_WAIT_S = 20.0
#: How long a model is skipped after a quota error that gave no retry-after.
DEFAULT_EXHAUSTED_S = 60.0
#: Statuses that mean "this provider is struggling" - try the next model.
_TRANSIENT = {500, 502, 503, 504, 529}


@dataclass(frozen=True)
class ModelSpec:
    name: str
    base_url: str
    api_key: str | None
    kind: Literal["openai", "anthropic"] = "openai"


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Delta:
    """A piece of a streamed reply."""

    text: str = ""
    model: str = ""
    #: Set on the last delta of a reply, when the provider reports it.
    usage: Usage | None = None


@dataclass
class Completion:
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class AllModelsExhausted(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Every model is out of quota for {retry_after:.0f}s")
        self.retry_after = retry_after


def model_chain(settings: Settings) -> list[ModelSpec]:
    """The configured models, in order of preference.

    ``CHAT_MODELS`` is a JSON list of ``{"name", "base_url", "api_key_env",
    "kind"}``. Without it, ``CHAT_MODEL`` and ``CHAT_FALLBACK_MODELS`` share
    ``CHAT_API_BASE_URL`` and ``CHAT_API_KEY``.
    """
    if settings.chat_models.strip():
        specs = []
        for entry in json.loads(settings.chat_models):
            key_env = entry.get("api_key_env")
            specs.append(
                ModelSpec(
                    name=entry["name"],
                    base_url=entry["base_url"].rstrip("/"),
                    api_key=os.environ.get(key_env) if key_env else None,
                    kind=entry.get("kind", "openai"),
                )
            )
        return specs
    if not settings.chat_api_key:
        return []
    return [
        ModelSpec(name, settings.chat_api_base_url.rstrip("/"), settings.chat_api_key)
        for name in dict.fromkeys((settings.chat_model, *settings.fallback_models))
    ]


class ExhaustionStore:
    """Which models are out of quota, and until when.

    Shared through Redis so every worker skips an exhausted model; falls back
    to this process's memory when Redis is unavailable.
    """

    PREFIX = "llm:exhausted:"

    def __init__(self, redis=None) -> None:
        self._redis = redis
        self._local: dict[str, float] = {}

    async def remaining(self, model: str) -> float:
        if self._redis is not None:
            try:
                ttl = await asyncio.to_thread(self._redis.pttl, self.PREFIX + model)
                if ttl and ttl > 0:
                    return ttl / 1000
            except Exception:  # noqa: BLE001 - fall back to local memory
                logger.warning("Redis unavailable for quota state; using memory")
        return max(0.0, self._local.get(model, 0.0) - time.monotonic())

    async def mark(self, model: str, seconds: float) -> None:
        seconds = max(1.0, seconds)
        self._local[model] = time.monotonic() + seconds
        if self._redis is not None:
            try:
                await asyncio.to_thread(
                    self._redis.set, self.PREFIX + model, "1", px=int(seconds * 1000)
                )
            except Exception:  # noqa: BLE001
                logger.warning("Could not share quota state for %s", model)


class ModelRouter:
    def __init__(
        self,
        chain: list[ModelSpec],
        store: ExhaustionStore,
        *,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not chain:
            raise ValueError("No language model is configured")
        self._chain = chain
        self._store = store
        self._timeout = httpx.Timeout(timeout_s, connect=10.0)
        self._transport = transport

    async def current_model(self) -> str:
        """The model the next request will try first."""
        for spec in self._chain:
            if await self._store.remaining(spec.name) <= 0:
                return spec.name
        return self._chain[0].name

    async def complete(
        self, system: str, user: str, max_tokens: int = 3000
    ) -> Completion:
        text, model, usage = [], "", Usage()
        async for delta in self.stream(system, user, max_tokens):
            text.append(delta.text)
            model = delta.model or model
            usage = delta.usage or usage
        return Completion("".join(text), model, usage)

    async def stream(
        self, system: str, user: str, max_tokens: int = 3000
    ) -> AsyncIterator[Delta]:
        # Generous max_tokens on purpose: reasoning models (gpt-oss) spend
        # part of it thinking and return nothing under a tight cap.
        soonest = float("inf")
        for spec in self._chain:
            remaining = await self._store.remaining(spec.name)
            if remaining > 0:
                soonest = min(soonest, remaining)
                continue
            for attempt in range(2):
                started = False
                try:
                    async for delta in self._stream_one(spec, system, user, max_tokens):
                        started = True
                        yield delta
                    return
                except ProviderError as exc:
                    if started:
                        raise
                    if exc.status == 429:
                        wait = exc.retry_after
                        if (
                            attempt == 0
                            and wait is not None
                            and wait <= MAX_RETRY_WAIT_S
                        ):
                            await asyncio.sleep(wait)
                            continue
                        wait = wait or DEFAULT_EXHAUSTED_S
                        await self._store.mark(spec.name, wait)
                        soonest = min(soonest, wait)
                        logger.warning("%s out of quota for %.0fs", spec.name, wait)
                        break
                    if exc.status in _TRANSIENT or exc.status is None:
                        logger.warning(
                            "%s failed (%s); trying the next model", spec.name, exc
                        )
                        break
                    raise
        raise AllModelsExhausted(
            soonest if soonest != float("inf") else DEFAULT_EXHAUSTED_S
        )

    async def _stream_one(
        self, spec: ModelSpec, system: str, user: str, max_tokens: int
    ) -> AsyncIterator[Delta]:
        adapter = _anthropic if spec.kind == "anthropic" else _openai
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            try:
                async for delta in adapter(client, spec, system, user, max_tokens):
                    yield delta
            except httpx.HTTPError as exc:
                raise ProviderError(f"{spec.name}: {exc.__class__.__name__}") from exc


async def _raise_for_status(response: httpx.Response, spec: ModelSpec) -> None:
    if response.status_code < 400:
        return
    body = (await response.aread()).decode("utf-8", "replace")[:300]
    raise ProviderError(
        f"{spec.name} returned {response.status_code}: {body}",
        status=response.status_code,
        retry_after=_retry_after(response.headers.get("retry-after")),
    )


async def _openai(client, spec, system, user, max_tokens) -> AsyncIterator[Delta]:
    headers = {"Content-Type": "application/json"}
    if spec.api_key:
        headers["Authorization"] = f"Bearer {spec.api_key}"
    payload = {
        "model": spec.name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if "api.openai.com" in spec.base_url:
        payload["stream_options"] = {"include_usage": True}
    async with client.stream(
        "POST", f"{spec.base_url}/chat/completions", headers=headers, json=payload
    ) as response:
        await _raise_for_status(response, spec)
        usage = None
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            reported = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
            if reported:
                usage = Usage(
                    reported.get("prompt_tokens", 0),
                    reported.get("completion_tokens", 0),
                )
            for choice in chunk.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield Delta(text=text, model=spec.name)
        yield Delta(model=spec.name, usage=usage or _estimate(system, user))


async def _anthropic(client, spec, system, user, max_tokens) -> AsyncIterator[Delta]:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": spec.api_key or "",
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": spec.name,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "stream": True,
    }
    base = spec.base_url or "https://api.anthropic.com"
    async with client.stream(
        "POST", f"{base}/v1/messages", headers=headers, json=payload
    ) as response:
        await _raise_for_status(response, spec)
        usage = Usage()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            kind = event.get("type")
            if kind == "message_start":
                usage.tokens_in = (
                    event["message"].get("usage", {}).get("input_tokens", 0)
                )
            elif kind == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield Delta(text=delta["text"], model=spec.name)
            elif kind == "message_delta":
                usage.tokens_out = (event.get("usage") or {}).get("output_tokens", 0)
            elif kind == "error":
                error = event.get("error") or {}
                status = 529 if error.get("type") == "overloaded_error" else None
                raise ProviderError(
                    f"{spec.name}: {error.get('message')}", status=status
                )
        yield Delta(model=spec.name, usage=usage)


def _estimate(system: str, user: str) -> Usage:
    """A rough count when the provider reports none: ~4 characters a token."""
    return Usage(tokens_in=(len(system) + len(user)) // 4)


def _retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None
