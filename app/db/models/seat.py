import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import SeatStatusEnum, SeatTypeEnum
from app.db.models.mixins import AuditMixin
from app.db.models.types import str_enum


class Seat(AuditMixin, Base):
    __tablename__ = "seat"
    __table_args__ = (
        UniqueConstraint("show_id", "seat_id", name="uq_show_seat"),
        Index("ix_seat_show_status", "show_id", "status"),
        CheckConstraint("price_paise >= 0", name="ck_seat_price_non_negative"),
        # A seat has an owner exactly when it is not available.
        CheckConstraint(
            "(status = 'available') = (reservation_id IS NULL)",
            name="ck_seat_owner_matches_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("show.id"), nullable=False)
    # Human-facing seat label, e.g. "A12". Unique within a show.
    seat_id: Mapped[str] = mapped_column(String(100), nullable=False)
    seat_type: Mapped[SeatTypeEnum] = mapped_column(
        str_enum(SeatTypeEnum, "seat_type"), nullable=False, default=SeatTypeEnum.REGULAR
    )
    # Money is integer paise, never float. Priced per seat so seat types can differ.
    price_paise: Mapped[int] = mapped_column(nullable=False)
    # The column every reservation will race on: the atomic step is a
    # conditional UPDATE ... WHERE status = 'available'.
    status: Mapped[SeatStatusEnum] = mapped_column(
        str_enum(SeatStatusEnum, "seat_status"), nullable=False, default=SeatStatusEnum.AVAILABLE
    )
    # Current owner; NULL while available. History lives in reservation.seat_ids.
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservation.id"), nullable=True
    )

    show: Mapped["Show"] = relationship(back_populates="seats")  # noqa: F821
