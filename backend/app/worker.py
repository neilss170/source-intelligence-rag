"""The ingestion worker: ``arq app.worker.WorkerSettings``.

Indexing is CPU-bound (embedding), so it runs off the event loop in a thread,
two documents at a time per worker. Scale out by running more workers.
"""

import asyncio
import datetime as dt
import logging
import uuid

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.db.models import Document
from app.db.session import get_sessionmaker
from app.ingest.pipeline import index_document
from app.ingest.queue import INGEST_JOB, job_id
from app.ingest.storage import get_storage
from app.services.dense_retriever import load_encoder

logger = logging.getLogger(__name__)

#: Documents left in these states longer than this are re-queued: their job
#: was lost (Redis down at upload time) or their worker died mid-way.
STALE_AFTER = {
    "uploaded": dt.timedelta(minutes=2),
    "indexing": dt.timedelta(minutes=30),
}


def run_ingestion(document_id: uuid.UUID) -> str:
    with get_sessionmaker()() as db:
        return index_document(db, document_id, get_storage())


async def ingest_document(ctx, document_id: str) -> str:
    return await asyncio.to_thread(run_ingestion, uuid.UUID(document_id))


def stale_document_ids(now: dt.datetime | None = None) -> list[uuid.UUID]:
    now = now or dt.datetime.now(dt.UTC)
    with get_sessionmaker()() as db:
        return list(
            db.scalars(
                select(Document.id).where(
                    or_(
                        *(
                            (Document.status == status)
                            & (Document.created_at < now - age)
                            for status, age in STALE_AFTER.items()
                        )
                    )
                )
            )
        )


async def requeue_stale(ctx) -> int:
    ids = await asyncio.to_thread(stale_document_ids)
    for document_id in ids:
        await ctx["redis"].enqueue_job(
            INGEST_JOB, str(document_id), _job_id=job_id(document_id)
        )
    if ids:
        logger.info("Re-queued %d stale document(s)", len(ids))
    return len(ids)


async def startup(ctx) -> None:
    # Load the embedding model before the first job, not during it.
    await asyncio.to_thread(load_encoder, get_settings().dense_model)
    await requeue_stale(ctx)


class WorkerSettings:
    functions = [ingest_document]
    cron_jobs = [cron(requeue_stale, minute=set(range(0, 60, 5)), run_at_startup=False)]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 2
    job_timeout = 900
    # A finished job's id is kept briefly, so a duplicate enqueue right after
    # completion does not index the same document twice.
    keep_result = 60
    # How often the worker records that it is alive, for `arq --check`.
    health_check_interval = 30
