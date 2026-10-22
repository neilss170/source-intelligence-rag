import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import UsageDaily


def today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def tokens_used_today(db: Session, user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(
                func.coalesce(func.sum(UsageDaily.tokens_in + UsageDaily.tokens_out), 0)
            ).where(UsageDaily.user_id == user_id, UsageDaily.day == today())
        )
    )


def record_usage(
    db: Session, user_id: uuid.UUID, model: str, tokens_in: int, tokens_out: int
) -> None:
    """Add one model call to the user's daily totals (an atomic upsert)."""
    statement = insert(UsageDaily).values(
        user_id=user_id,
        model=model,
        day=today(),
        requests=1,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[UsageDaily.user_id, UsageDaily.model, UsageDaily.day],
            set_={
                "requests": UsageDaily.requests + 1,
                "tokens_in": UsageDaily.tokens_in + statement.excluded.tokens_in,
                "tokens_out": UsageDaily.tokens_out + statement.excluded.tokens_out,
            },
        )
    )
