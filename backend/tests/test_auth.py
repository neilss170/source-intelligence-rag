from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.db.models import AuthSession, User


def test_sign_up_signs_in_and_creates_a_workspace(make_client, sign_up) -> None:
    client = make_client()
    body = sign_up(client, "  Neil@Example.com ", name="Neil")

    me = client.get("/api/me")

    assert me.status_code == 200
    assert me.json()["user"] == {
        **body["user"],
        "email": "neil@example.com",
        "name": "Neil",
    }
    assert me.json()["workspace"]["name"] == "My workspace"
    assert client.cookies.get("si_session")
    assert client.cookies.get("si_csrf") == body["csrf_token"]


def test_email_is_unique_regardless_of_case(make_client, sign_up) -> None:
    sign_up(make_client(), "neil@example.com")
    response = make_client().post(
        "/api/auth/signup",
        json={"email": "NEIL@example.com", "password": "another long password"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_weak_and_malformed_sign_ups_are_rejected(make_client) -> None:
    client = make_client()
    short = client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "short"}
    )
    same = client.post(
        "/api/auth/signup",
        json={"email": "longemail@example.com", "password": "longemail@example.com"},
    )
    bad_email = client.post(
        "/api/auth/signup", json={"email": "not-an-email", "password": "long enough pw"}
    )

    assert short.status_code == 422 and short.json()["error"]["code"] == "weak_password"
    assert same.status_code == 422 and same.json()["error"]["code"] == "weak_password"
    assert bad_email.status_code == 422
    assert bad_email.json()["error"]["code"] == "invalid_request"
    assert bad_email.json()["error"]["fields"][0]["field"] == "email"


def test_log_in_and_out(make_client, sign_up) -> None:
    sign_up(make_client(), "neil@example.com", password="correct horse battery")
    client = make_client()

    wrong = client.post(
        "/api/auth/login",
        json={"email": "neil@example.com", "password": "nope nope nope"},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"email": "who@example.com", "password": "nope nope nope"},
    )
    ok = client.post(
        "/api/auth/login",
        json={"email": "NEIL@example.com", "password": "correct horse battery"},
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert ok.status_code == 200
    stolen_cookie = client.cookies.get("si_session")

    client.headers["X-CSRF-Token"] = ok.json()["csrf_token"]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401

    replay = make_client()
    replay.cookies.set("si_session", stolen_cookie)
    assert replay.get("/api/me").status_code == 401


def test_secrets_are_stored_hashed(make_client, sign_up, db) -> None:
    client = make_client()
    sign_up(client, "neil@example.com", password="correct horse battery")

    with Session(db) as session:
        user = session.scalar(select(User))
        stored = session.scalar(select(AuthSession))

    assert user.password_hash.startswith("$argon2id$")
    assert "correct horse battery" not in user.password_hash
    assert stored.token_hash != client.cookies.get("si_session").encode()
    assert len(stored.token_hash) == 32


def test_state_changes_need_the_csrf_header(make_client, sign_up) -> None:
    client = make_client()
    csrf = sign_up(client, "neil@example.com")["csrf_token"]
    del client.headers["X-CSRF-Token"]

    missing = client.post("/api/chats", json={"title": "x"})
    wrong = client.post(
        "/api/chats", json={"title": "x"}, headers={"X-CSRF-Token": "no"}
    )
    right = client.post(
        "/api/chats", json={"title": "x"}, headers={"X-CSRF-Token": csrf}
    )
    reads_are_fine = client.get("/api/chats")

    assert missing.status_code == wrong.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"
    assert right.status_code == 201
    assert reads_are_fine.status_code == 200


def test_expired_sessions_are_refused(make_client, sign_up, db) -> None:
    client = make_client()
    sign_up(client, "neil@example.com")
    with db.begin() as connection:
        connection.execute(
            update(AuthSession.__table__).values(
                expires_at=datetime.now(UTC) - timedelta(minutes=1)
            )
        )

    assert client.get("/api/me").status_code == 401
    with db.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sessions")).scalar() == 0


def test_errors_carry_a_code_message_and_request_id(make_client, sign_up) -> None:
    response = make_client().get("/api/me", headers={"X-Request-ID": "trace-12345678"})

    assert response.status_code == 401
    error = response.json()["error"]
    assert error == {
        "code": "not_authenticated",
        "message": "Sign in to continue.",
        "request_id": "trace-12345678",
    }
    assert response.json()["detail"] == "Sign in to continue."
    assert response.headers["X-Request-ID"] == "trace-12345678"
