"""No user can reach another user's data through any endpoint.

``test_every_route_is_covered`` lists every API route and fails when a new one
appears without a decision here, so isolation is checked by construction
rather than remembered.
"""

import uuid

import pytest

from app.main import app

PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/ready"),
    ("POST", "/api/auth/signup"),
    ("POST", "/api/auth/login"),
}

#: Routes still serving the single shared workspace of the prototype. They
#: move under authentication with the document pipeline (milestone 2) and the
#: streaming chat endpoint (milestone 4); until then they are listed here so
#: the gap stays visible. This set must be empty when milestone 4 is done.
LEGACY_UNSCOPED_ROUTES = {
    ("GET", "/api/documents"),
    ("POST", "/api/documents"),
    ("DELETE", "/api/documents/{document_id}"),
    ("POST", "/api/query"),
}

CHAT_ROUTES = [
    ("GET", "/api/chats/{chat_id}/messages", None),
    ("PATCH", "/api/chats/{chat_id}", {"title": "stolen"}),
    ("DELETE", "/api/chats/{chat_id}", None),
]


def _api_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        if route.path.startswith("/api/")
        for method in getattr(route, "methods", set()) - {"HEAD"}
    }


def test_every_route_is_covered() -> None:
    authenticated = _api_routes() - PUBLIC_ROUTES - LEGACY_UNSCOPED_ROUTES
    known = {
        ("GET", "/api/me"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/chats"),
        ("POST", "/api/chats"),
    } | {(m, p) for m, p, _ in CHAT_ROUTES}

    assert authenticated == known, (
        "A route was added or removed. Add it to this file's isolation tests, "
        "or to PUBLIC_ROUTES if it is meant to be public."
    )


@pytest.mark.parametrize(
    ("method", "path"),
    sorted(_api_routes() - PUBLIC_ROUTES - LEGACY_UNSCOPED_ROUTES),
)
def test_signed_out_callers_are_refused(make_client, method, path) -> None:
    client = make_client()
    response = client.request(method, path.replace("{chat_id}", str(uuid.uuid4())))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize(("method", "path", "body"), CHAT_ROUTES)
def test_another_users_chat_looks_like_it_does_not_exist(
    make_client, sign_up, method, path, body
) -> None:
    alice, bob = make_client(), make_client()
    sign_up(alice, "alice@example.com")
    sign_up(bob, "bob@example.com")
    chat_id = alice.post("/api/chats", json={"title": "Alice's plans"}).json()["id"]
    missing_id = str(uuid.uuid4())

    stolen = bob.request(method, path.format(chat_id=chat_id), json=body)
    absent = bob.request(method, path.format(chat_id=missing_id), json=body)

    assert stolen.status_code == absent.status_code == 404
    assert stolen.json()["error"]["message"] == absent.json()["error"]["message"]
    assert alice.get("/api/chats").json()[0]["title"] == "Alice's plans"


def test_chat_lists_only_show_your_own_chats(make_client, sign_up) -> None:
    alice, bob = make_client(), make_client()
    sign_up(alice, "alice@example.com")
    sign_up(bob, "bob@example.com")
    alice.post("/api/chats", json={"title": "Alice"})
    bob.post("/api/chats", json={"title": "Bob"})

    assert [c["title"] for c in alice.get("/api/chats").json()] == ["Alice"]
    assert [c["title"] for c in bob.get("/api/chats").json()] == ["Bob"]


def test_chat_lifecycle(make_client, sign_up) -> None:
    client = make_client()
    sign_up(client, "neil@example.com")

    first = client.post("/api/chats", json={"title": "First"}).json()
    second = client.post("/api/chats", json={}).json()
    renamed = client.patch(f"/api/chats/{first['id']}", json={"title": "Renamed"})

    assert second["title"] == "New chat"
    assert renamed.status_code == 200 and renamed.json()["title"] == "Renamed"
    assert [c["title"] for c in client.get("/api/chats").json()] == [
        "Renamed",
        "New chat",
    ]
    assert client.get(f"/api/chats/{first['id']}/messages").json() == []
    assert client.delete(f"/api/chats/{first['id']}").status_code == 204
    assert [c["id"] for c in client.get("/api/chats").json()] == [second["id"]]
