"""Rate limits (milestone 6)."""

import pytest

from app.core import rate_limit
from app.core.rate_limit import Limit


@pytest.fixture
def tight(monkeypatch):
    """Limits small enough to reach in a test."""
    monkeypatch.setattr(rate_limit, "AUTH", Limit("auth", 3, 900, "Too many."))
    monkeypatch.setattr(rate_limit, "UPLOADS", Limit("uploads", 2, 3600, "Slow."))
    monkeypatch.setattr(rate_limit, "QUESTIONS", Limit("questions", 2, 60, "Wait."))


def test_sign_in_attempts_are_limited_per_address(make_client, tight) -> None:
    client = make_client()
    attempts = [
        client.post(
            "/api/auth/login",
            json={"email": f"user{n}@example.com", "password": "not the password"},
        )
        for n in range(4)
    ]

    assert [a.status_code for a in attempts] == [401, 401, 401, 429]
    blocked = attempts[-1]
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert 0 < int(blocked.headers["Retry-After"]) <= 900


def test_guessing_one_account_is_limited_from_any_address(
    make_client, tight, monkeypatch
) -> None:
    addresses = iter(f"10.0.0.{n}" for n in range(10))
    monkeypatch.setattr(rate_limit, "client_ip", lambda request: next(addresses))
    client = make_client()

    codes = [
        client.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": "guess guess guess"},
        ).status_code
        for _ in range(4)
    ]

    assert codes == [401, 401, 401, 429]


def test_uploads_and_questions_are_limited_per_user(
    make_client, sign_up, ingestion, tight
) -> None:
    client = make_client()
    sign_up(client, "neil@example.com")
    uploads = [
        client.post(
            "/api/documents",
            files=[("files", (f"n{n}.txt", f"note {n}".encode(), "text/plain"))],
        ).status_code
        for n in range(3)
    ]
    chat_id = client.post("/api/chats", json={}).json()["id"]
    # The model is never reached: the limit is checked before streaming.
    questions = [
        client.post(
            f"/api/chats/{chat_id}/messages", json={"question": "hi", "scope": "auto"}
        ).status_code
        for _ in range(3)
    ]

    assert uploads == [202, 202, 429]
    assert questions[-1] == 429


def test_the_limiter_fails_open_when_redis_is_down(make_client, monkeypatch) -> None:
    class Down:
        def pipeline(self):
            raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limit, "get_redis", lambda: Down())
    client = make_client()

    response = client.post(
        "/api/auth/login", json={"email": "a@example.com", "password": "x"}
    )

    assert response.status_code == 401
