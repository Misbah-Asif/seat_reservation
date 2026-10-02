from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import AuditMixin


class Show(AuditMixin, Base):
    __tablename__ = "show"
    __table_args__ = (
        CheckConstraint("per_user_limit >= 1", name="ck_show_per_user_limit_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # No default here: the service always passes it (request value or settings).
    per_user_limit: Mapped[int] = mapped_column(nullable=False)

    seats: Mapped[list["Seat"]] = relationship(back_populates="show", order_by="Seat.id")  # noqa: F821
