import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import ReservationStatusEnum, SeatStatusEnum
from app.db.models.reservation import Reservation
from app.db.models.seat import Seat


class ReservationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def lock_user(self, user_id: str) -> None:
        """Serialize this user's reserve requests until the transaction ends.

        A transaction-level advisory lock keyed on the user id: requests from
        the same user run one at a time, everyone else is unaffected. That makes
        the idempotency lookup and the per-user seat count race-free without a
        table lock. Released automatically on commit or rollback.
        """
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"),
            {"user_id": user_id},
        )

    async def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> Reservation | None:
        result = await self.db.execute(
            select(Reservation).where(
                Reservation.user_id == user_id,
                Reservation.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def count_user_seats(self, show_id: int, user_id: str) -> int:
        """Seats this user currently holds or has confirmed for the show."""
        result = await self.db.execute(
            select(func.coalesce(func.sum(func.cardinality(Reservation.seat_labels)), 0)).where(
                Reservation.show_id == show_id,
                Reservation.user_id == user_id,
                Reservation.status != ReservationStatusEnum.CANCELLED,
            )
        )
        return result.scalar_one()

    async def find_taken_seats(self, show_id: int, seat_labels: list[str]) -> list[str]:
        """Plain read, no locks: a cheap early decline during a hot-seat storm.

        Not the source of truth (it can be stale the moment it returns); the
        locked check in the service is. It only lets the losers of an
        already-decided seat leave without queueing on its row lock.
        """
        result = await self.db.execute(
            select(Seat.seat_label).where(
                Seat.show_id == show_id,
                Seat.seat_label.in_(seat_labels),
                Seat.status != SeatStatusEnum.AVAILABLE,
            )
        )
        return sorted(result.scalars())

    async def lock_seats(self, show_id: int, seat_labels: list[str]) -> list[Seat]:
        """Row-lock the requested seats until the transaction ends.

        Concurrent requests for any of these seats wait here, and when they get
        the lock they see the committed status, so the availability check that
        follows can't be raced. Locks are taken in seat_label order, the same order
        for every request, so two multi-seat requests can't deadlock.
        """
        result = await self.db.execute(
            select(Seat)
            .where(Seat.show_id == show_id, Seat.seat_label.in_(seat_labels))
            .order_by(Seat.seat_label)
            .with_for_update()
        )
        return list(result.scalars())

    async def create(
        self,
        show_id: int,
        user_id: str,
        idempotency_key: str,
        seat_labels: list[str],
        amount_paise: int,
        status: ReservationStatusEnum,
    ) -> Reservation:
        reservation = Reservation(
            show_id=show_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            seat_labels=seat_labels,
            amount_paise=amount_paise,
            status=status,
        )
        self.db.add(reservation)
        # The row must exist before seats can point at it (seat.reservation_id FK).
        await self.db.flush()
        return reservation

    async def get_for_update(self, reservation_id: uuid.UUID) -> Reservation | None:
        result = await self.db.execute(
            select(Reservation).where(Reservation.id == reservation_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def lock_reservation_seats(self, reservation_id: uuid.UUID) -> list[Seat]:
        """Row-lock the seats this reservation owns, in seat_label order (same
        order as reserve's lock_seats, so cancel and reserve can't deadlock)."""
        result = await self.db.execute(
            select(Seat)
            .where(Seat.reservation_id == reservation_id)
            .order_by(Seat.seat_label)
            .with_for_update()
        )
        return list(result.scalars())

    async def release_seats(self, reservation_id: uuid.UUID) -> None:
        # Guarded by reservation_id, never by label: a seat that now belongs to
        # someone else can't match, so a release can't free it.
        await self.db.execute(
            update(Seat)
            .where(Seat.reservation_id == reservation_id)
            .values(status=SeatStatusEnum.AVAILABLE, reservation_id=None)
        )

    async def assign_seats(
        self, seat_pks: list[int], reservation_id: uuid.UUID, status: SeatStatusEnum
    ) -> None:
        # One UPDATE for all seats; they're already locked by lock_seats.
        await self.db.execute(
            update(Seat)
            .where(Seat.id.in_(seat_pks))
            .values(status=status, reservation_id=reservation_id)
        )
