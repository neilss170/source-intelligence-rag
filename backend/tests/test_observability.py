"""Logs and metrics (milestone 6)."""

import json
import logging
import uuid

from app.core.errors import request_id_var
from app.core.observability import JsonFormatter


def _metric(text: str, name: str, **labels) -> float:
    wanted = ",".join(f'{k}="{v}"' for k, v in labels.items())
    for line in text.splitlines():
        if line.startswith(f"{name}{{") and all(
            f'{k}="{v}"' in line for k, v in labels.items()
        ):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"{name}{{{wanted}}} not in metrics")


def test_requests_are_counted_by_route_template(make_client, sign_up) -> None:
    client = make_client()
    sign_up(client, "neil@example.com")
    for _ in range(2):
        client.get(f"/api/chats/{uuid.uuid4()}/messages")

    text = client.get("/metrics").text

    # One series for the route, not one per chat ID.
    assert (
        _metric(
            text,
            "http_requests_total",
            method="GET",
            route="/api/chats/{chat_id}/messages",
            status="404",
        )
        >= 2
    )
    assert "documents{" in text and "ingestion_queue_depth" in text


def test_json_logs_carry_the_request_id_and_extra_fields() -> None:
    record = logging.LogRecord(
        "app.test", logging.INFO, "", 0, "answer %s", ("ok",), None
    )
    record.tokens_in = 120
    token = request_id_var.set("req-1234abcd")
    try:
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert line["message"] == "answer ok"
    assert line["request_id"] == "req-1234abcd"
    assert line["tokens_in"] == 120
    assert line["level"] == "info"


def test_an_answer_updates_the_answer_metrics(make_client, sign_up, ingestion) -> None:
    from app.chat.deps import get_chat_service
    from app.chat.providers import Delta, Usage
    from app.chat.service import ChatService
    from app.core.config import get_settings
    from app.db.session import get_sessionmaker
    from app.main import app

    class Model:
        async def current_model(self):
            return "metrics-model"

        async def stream(self, system, user, max_tokens=3000):
            yield Delta(text="Hello there.", model="metrics-model")
            yield Delta(model="metrics-model", usage=Usage(70, 9))

    class Ranker:
        def score(self, query, evidence):
            return [1.0] * len(evidence)

    service = ChatService(
        settings=get_settings(),
        sessions=get_sessionmaker(),
        router=Model(),
        ranker=Ranker(),
    )
    app.dependency_overrides[get_chat_service] = lambda: service
    client = make_client()
    sign_up(client, "neil@example.com")
    chat_id = client.post("/api/chats", json={}).json()["id"]
    before = client.get("/metrics").text

    client.post(f"/api/chats/{chat_id}/messages", json={"question": "hi"})
    after = client.get("/metrics").text
    app.dependency_overrides.pop(get_chat_service, None)

    def value(text, name, **labels):
        try:
            return _metric(text, name, **labels)
        except AssertionError:
            return 0.0

    assert value(after, "answers_total", mode="general") == (
        value(before, "answers_total", mode="general") + 1
    )
    assert value(after, "llm_tokens_total", model="metrics-model", direction="in") == (
        value(before, "llm_tokens_total", model="metrics-model", direction="in") + 70
    )
    assert "answer_stage_seconds_bucket" in after
