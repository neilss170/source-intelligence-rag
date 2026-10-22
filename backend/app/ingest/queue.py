import logging
import uuid
from typing import Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

logger = logging.getLogger(__name__)

INGEST_JOB = "ingest_document"


def job_id(document_id: uuid.UUID) -> str:
    # One job per document: enqueueing twice while it waits is a no-op.
    return f"ingest:{document_id}"


class IngestionQueue(Protocol):
    async def enqueue(self, document_id: uuid.UUID) -> None: ...


class ArqQueue:
    def __init__(self) -> None:
        self._pool: ArqRedis | None = None

    async def enqueue(self, document_id: uuid.UUID) -> None:
        if self._pool is None:
            self._pool = await create_pool(
                RedisSettings.from_dsn(get_settings().redis_url)
            )
        await self._pool.enqueue_job(
            INGEST_JOB, str(document_id), _job_id=job_id(document_id)
        )


_queue = ArqQueue()


def get_queue() -> IngestionQueue:
    return _queue
