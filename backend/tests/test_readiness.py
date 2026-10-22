from app.api.routes import health


def test_ready_when_database_and_redis_answer(make_client) -> None:
    response = make_client().get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok"},
    }


def test_not_ready_when_redis_is_down(make_client, monkeypatch) -> None:
    class DownRedis:
        def ping(self):
            raise ConnectionError("refused")

    monkeypatch.setattr(health, "get_redis", lambda: DownRedis())
    response = make_client().get("/api/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "unavailable"}


def test_not_ready_while_models_load(make_client, monkeypatch) -> None:
    monkeypatch.setattr(health.warmup, "status", lambda: "loading")
    loading = make_client().get("/api/ready")
    monkeypatch.setattr(health.warmup, "status", lambda: "ready")
    ready = make_client().get("/api/ready")

    assert loading.status_code == 503
    assert loading.json()["checks"]["models"] == "loading"
    assert ready.status_code == 200
    assert ready.json()["checks"]["models"] == "ok"
