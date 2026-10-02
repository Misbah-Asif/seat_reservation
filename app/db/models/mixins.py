from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class AuditMixin:
    """Timestamps for every table. Lifecycle (cancelled, etc.) lives in each
    table's `status` column, not in an is_active flag.

    updated_at is set by SQLAlchemy on every UPDATE the app sends (ORM and
    Core update()); manual SQL in psql does not touch it."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
