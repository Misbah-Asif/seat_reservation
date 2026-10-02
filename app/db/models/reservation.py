from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import ReservationStatusEnum
from app.db.models.mixins import AuditMixin
from app.db.models.types import str_enum


class Reservation(AuditMixin, Base):
    """One row per booking request, however many seats it covers."""

    __tablename__ = "reservation"
    __table_args__ = (
        # Exactly-once: a key can only ever create one reservation per user.
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_idemp"),
        Index("ix_reservation_show_user", "show_id", "user_id"),
        CheckConstraint("amount_paise >= 0", name="ck_reservation_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("show.id"), nullable=False)
    # Subject of the auth token, never taken from the request body.
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Snapshot of the seats booked, always stored sorted. Used to replay the
    # original response, and to spot a reused key: same key with a different
    # show_id or seat_ids is a 409. Current ownership is seat.reservation_id.
    seat_ids: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    # Sum of seat prices at booking time; later price changes don't touch it.
    amount_paise: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[ReservationStatusEnum] = mapped_column(
        str_enum(ReservationStatusEnum, "reservation_status"), nullable=False
    )
