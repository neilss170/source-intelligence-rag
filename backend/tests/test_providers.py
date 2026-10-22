"""Model providers and the fallback chain (milestone 4)."""

import asyncio
import json

import httpx
import pytest

from app.chat import providers
from app.chat.providers import (
    AllModelsExhausted,
    ExhaustionStore,
    ModelRouter,
    ModelSpec,
    ProviderError,
    model_chain,
)
from app.core.config import Settings

BIG = ModelSpec("big", "https://groq.test/v1", "key")
SMALL = ModelSpec("small", "https://groq.test/v1", "key")
CLAUDE = ModelSpec("claude-test", "https://anthropic.test", "key", kind="anthropic")


def openai_stream(*texts: str, usage=(12, 3)) -> bytes:
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) for t in texts
    ]
    lines.append(
        "data: "
        + json.dumps(
            {
                "choices": [],
                "x_groq": {
                    "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}
                },
            }
        )
    )
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def anthropic_stream(*texts: str) -> bytes:
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 40}}},
        *(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}}
            for t in texts
        ),
        {"type": "message_delta", "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    ]
    return "".join(
        f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events
    ).encode()


class Server:
    """Answers per model name; a response is (status, body, headers)."""

    def __init__(self, **by_model) -> None:
        self.by_model = {name: list(responses) for name, responses in by_model.items()}
        self.seen: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"].replace("-", "_")
        self.seen.append(model)
        status, body, headers = self.by_model[model].pop(0)
        return httpx.Response(status, content=body, headers=headers)


def router(server, *chain, store=None) -> ModelRouter:
    return ModelRouter(
        list(chain),
        store or ExhaustionStore(None),
        transport=httpx.MockTransport(server),
    )


def run(coro):
    return asyncio.run(coro)


def test_openai_format_streams_text_and_usage() -> None:
    server = Server(big=[(200, openai_stream("Hel", "lo"), {})])

    async def collect():
        return [d async for d in router(server, BIG).stream("s", "u")]

    deltas = run(collect())

    assert "".join(d.text for d in deltas) == "Hello"
    assert deltas[-1].usage.tokens_in == 12 and deltas[-1].usage.tokens_out == 3


def test_anthropic_format_streams_text_and_usage() -> None:
    server = Server(claude_test=[(200, anthropic_stream("Hi ", "there"), {})])

    completion = run(router(server, CLAUDE).complete("s", "u"))

    assert completion.text == "Hi there"
    assert completion.model == "claude-test"
    assert (completion.usage.tokens_in, completion.usage.tokens_out) == (40, 7)


def test_an_exhausted_model_is_skipped_until_it_resets() -> None:
    server = Server(
        big=[(429, b"daily limit", {"retry-after": "600"})],
        small=[
            (200, openai_stream("from small"), {}),
            (200, openai_stream("again"), {}),
        ],
    )
    chain = router(server, BIG, SMALL)

    first = run(chain.complete("s", "u"))
    second = run(chain.complete("s", "u"))

    assert first.text == "from small" and first.model == "small"
    assert second.text == "again"
    assert server.seen == ["big", "small", "small"]
    assert run(chain.current_model()) == "small"


def test_a_short_rate_limit_is_waited_out(monkeypatch) -> None:
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)
    server = Server(
        big=[(429, b"slow down", {"retry-after": "2"}), (200, openai_stream("ok"), {})]
    )

    assert run(router(server, BIG, SMALL).complete("s", "u")).text == "ok"
    assert waits == [2.0]


def test_a_struggling_provider_hands_over_to_the_next() -> None:
    server = Server(
        big=[(503, b"unavailable", {})], small=[(200, openai_stream("ok"), {})]
    )

    assert run(router(server, BIG, SMALL).complete("s", "u")).model == "small"


def test_a_bad_request_is_not_hidden_by_falling_back() -> None:
    server = Server(big=[(400, b"bad model name", {})])

    with pytest.raises(ProviderError) as error:
        run(router(server, BIG, SMALL).complete("s", "u"))
    assert error.value.status == 400


def test_when_every_model_is_out_the_soonest_reset_is_reported() -> None:
    server = Server(
        big=[(429, b"x", {"retry-after": "900"})],
        small=[(429, b"x", {"retry-after": "300"})],
    )

    with pytest.raises(AllModelsExhausted) as error:
        run(router(server, BIG, SMALL).complete("s", "u"))
    assert error.value.retry_after == 300


def test_quota_state_is_shared_through_redis() -> None:
    from app.core.redis_client import get_redis

    redis = get_redis()
    redis.delete(ExhaustionStore.PREFIX + "shared-model")
    one, two = ExhaustionStore(redis), ExhaustionStore(redis)

    run(one.mark("shared-model", 30))

    assert 25 < run(two.remaining("shared-model")) <= 30
    redis.delete(ExhaustionStore.PREFIX + "shared-model")


def test_model_chain_from_settings(monkeypatch) -> None:
    simple = Settings(
        chat_api_key="k",
        chat_api_base_url="https://api.groq.com/openai/v1/",
        chat_model="openai/gpt-oss-120b",
        chat_fallback_models="openai/gpt-oss-20b",
        chat_models="",
    )
    monkeypatch.setenv("ANTHROPIC_KEY", "secret")
    explicit = Settings(
        chat_models=json.dumps(
            [
                {
                    "name": "claude-sonnet",
                    "base_url": "https://api.anthropic.com",
                    "api_key_env": "ANTHROPIC_KEY",
                    "kind": "anthropic",
                },
                {"name": "llama3.2:3b", "base_url": "http://localhost:11434/v1"},
            ]
        )
    )

    assert [(m.name, m.base_url) for m in model_chain(simple)] == [
        ("openai/gpt-oss-120b", "https://api.groq.com/openai/v1"),
        ("openai/gpt-oss-20b", "https://api.groq.com/openai/v1"),
    ]
    claude, local = model_chain(explicit)
    assert (claude.kind, claude.api_key) == ("anthropic", "secret")
    assert (local.kind, local.api_key) == ("openai", None)
    assert model_chain(Settings(chat_api_key=None, chat_models="")) == []


def test_model_options_are_sent_with_each_request() -> None:
    sent = []

    def server(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=openai_stream("ok"))

    spec = ModelSpec(
        "big", "https://groq.test/v1", "key", options={"reasoning_effort": "low"}
    )
    run(
        ModelRouter(
            [spec], ExhaustionStore(None), transport=httpx.MockTransport(server)
        ).complete("s", "u")
    )

    assert sent[0]["reasoning_effort"] == "low"
    assert model_chain(
        Settings(chat_api_key="k", chat_models="", chat_reasoning_effort="low")
    )[0].options == {"reasoning_effort": "low"}
