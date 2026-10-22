"""Shared fixtures.

Database tests run against a separate test database - never the one the app
uses - migrated with the real Alembic migrations, and emptied before each
test. ``docker compose up -d db redis`` provides both locally; CI starts them
as service containers.
"""

import os
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://si:si_dev_password@127.0.0.1:5433/source_intelligence_test",
)
# Point the app at the test database before anything reads the settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6380/15")
os.environ.setdefault("APP_ENV", "development")

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_database():
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from alembic import command

    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("CI"):
            raise
        pytest.skip(
            f"Test database unavailable ({exc.__class__.__name__}); "
            "run `docker compose up -d db redis`."
        )
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_database):
    """An empty database for each test."""
    from sqlalchemy import text

    from app.db.models import Base

    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with migrated_database.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield migrated_database


@pytest.fixture
def make_client(db):
    """A factory of API clients, each with its own cookie jar - one per user."""
    from fastapi.testclient import TestClient

    from app.main import app

    clients = []

    def make() -> TestClient:
        client = TestClient(app)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


@pytest.fixture
def sign_up():
    """Sign a client up and make it send the CSRF header from then on."""
    return _sign_up


def _sign_up(client, email: str, password: str = "correct horse battery", name=""):
    response = client.post(
        "/api/auth/signup", json={"email": email, "password": password, "name": name}
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


# -- ingestion -----------------------------------------------------------------


class FakeEncoder:
    """Deterministic unit vectors, so tests need no model download."""

    def encode(self, texts, normalize_embeddings=True, **kwargs):
        import hashlib

        import numpy as np

        rows = []
        for value in texts:
            seed = int(hashlib.sha1(value.encode()).hexdigest()[:8], 16)
            vector = np.random.default_rng(seed).normal(size=384)
            rows.append(vector / np.linalg.norm(vector))
        return np.asarray(rows, dtype=np.float32)


class InlineQueue:
    """Runs each queued document immediately, like a worker would."""

    def __init__(self, storage) -> None:
        self.storage = storage
        self.queued: list = []
        self.fail = False

    async def enqueue(self, document_id) -> None:
        from app.db.session import get_sessionmaker
        from app.ingest.pipeline import index_document

        if self.fail:
            raise ConnectionError("redis down")
        self.queued.append(document_id)
        with get_sessionmaker()() as db:
            index_document(db, document_id, self.storage)


@pytest.fixture
def ingestion(tmp_path, monkeypatch, db):
    """Uploads stored in a temp dir and indexed inline with a fake encoder."""
    from app.ingest import pipeline
    from app.ingest.queue import get_queue
    from app.ingest.storage import LocalFileStorage, get_storage
    from app.main import app

    storage = LocalFileStorage(tmp_path / "files")
    queue = InlineQueue(storage)
    monkeypatch.setattr(pipeline, "load_encoder", lambda name: FakeEncoder())
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue
    yield queue
    app.dependency_overrides.clear()
