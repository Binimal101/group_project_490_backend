from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow_aware() -> datetime:
    """Single source of truth for the `last_updated` default. Always returns
    a timezone-aware UTC datetime so JSON serialization carries a tz suffix
    and browsers can offset cleanly to the local timezone for display."""
    return datetime.now(timezone.utc)


class SQLModelLU(SQLModel):
    last_updated: datetime = Field(default_factory=utcnow_aware)
