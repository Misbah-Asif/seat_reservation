import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    IdempotencyKeyReused,
    PerUserLimitExceeded,
    ReservationNotFound,
    SeatsNotFound,
    SeatsUnavailable,
    ShowNotFound,
)
from app.db.models.enums import ReservationStatusEnum, SeatStatusEnum
from app.db.models.reservation import Reservation
from app.db.models.show import Show
from app.repositories.reservation_repository import ReservationRepository
from app.schemas.reservation import CreateReservationRequest, ReservationResponse


class ReservationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.reservations = ReservationRepository(db)

    async def create_reservation(
        self, show_id: int, user_id: str, payload: CreateReservationRequest
    ) -> tuple[ReservationResponse, bool]:
        """Reserve seats all-or-nothing. Returns (reservation, created).

        `created` is False for an idempotent replay, so the API can answer 200
        instead of 201: a retry must never look like a second winner.

        One transaction, locks always taken in the same order (this user's
        advisory lock, then seat rows sorted by seat_label), so no deadlocks.
        Every decline rolls back before raising, releasing locks immediately.
        """
        seat_labels = sorted(payload.seats)

        try:
            # 1. One request at a time per user: makes steps 2 and 4 race-free.
            await self.reservations.lock_user(user_id)

            # 2. Idempotency. Checked before seat availability, so the winner's
            #    retry gets its reservation back instead of "seat taken".
            existing = await self.reservations.get_by_idempotency_key(
                user_id, payload.idempotency_key
            )
            if existing is not None:
                if existing.show_id != show_id or existing.seat_labels != seat_labels:
                    raise IdempotencyKeyReused(idempotency_key=payload.idempotency_key)
                # Build before rollback: rollback expires loaded objects.
                replay = self._to_response(existing)
                await self.db.rollback()
                return replay, False

            show = await self.db.get(Show, show_id)
            if show is None:
                raise ShowNotFound(show_id=show_id)

            # 3. Cheap unlocked pre-check: storm losers leave without queueing.
            taken = await self.reservations.find_taken_seats(show_id, seat_labels)
            if taken:
                raise SeatsUnavailable(unavailable_seats=taken)

            # 4. Per-user limit. Safe without a seat lock: only this user's own
            #    requests can change this count, and they're serialized by step 1.
            held = await self.reservations.count_user_seats(show_id, user_id)
            if held + len(seat_labels) > show.per_user_limit:
                raise PerUserLimitExceeded(
                    per_user_limit=show.per_user_limit, held=held, requested=len(seat_labels)
                )

            # 5. The real decision: lock the seats, then check them under the lock.
            seats = await self.reservations.lock_seats(show_id, seat_labels)
            missing = sorted(set(seat_labels) - {s.seat_label for s in seats})
            if missing:
                raise SeatsNotFound(seats=missing)
            taken = [s.seat_label for s in seats if s.status != SeatStatusEnum.AVAILABLE]
            if taken:
                raise SeatsUnavailable(unavailable_seats=taken)

            # 6. Write. Price comes from the locked rows, so it can't change under us.
            reservation = await self.reservations.create(
                show_id=show_id,
                user_id=user_id,
                idempotency_key=payload.idempotency_key,
                seat_labels=seat_labels,
                amount_paise=sum(s.price_paise for s in seats),
                status=ReservationStatusEnum.CONFIRMED,
            )
            await self.reservations.assign_seats(
                [s.id for s in seats], reservation.id, SeatStatusEnum.CONFIRMED
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return self._to_response(reservation), True

    async def cancel_reservation(
        self, reservation_id: uuid.UUID, user_id: str
    ) -> ReservationResponse:
        """Cancel the caller's own reservation and free its seats.

        Lock order matches reserve: user lock, then the reservation row, then
        its seats in seat_label order, so cancel and reserve can't deadlock.
        Cancelling an already-cancelled reservation is a no-op that returns it.
        """
        try:
            # Same per-user lock as reserve: this user's reserves and cancels take
            # turns, so their held-seat count (the per-user limit) is never raced.
            await self.reservations.lock_user(user_id)

            reservation = await self.reservations.get_for_update(reservation_id)
            # Someone else's booking looks exactly like a missing one.
            if reservation is None or reservation.user_id != user_id:
                raise ReservationNotFound(reservation_id=str(reservation_id))

            if reservation.status != ReservationStatusEnum.CANCELLED:
                await self.reservations.lock_reservation_seats(reservation.id)
                await self.reservations.release_seats(reservation.id)
                reservation.status = ReservationStatusEnum.CANCELLED

            # Build before commit/rollback so nothing needs reloading afterwards.
            result = self._to_response(reservation)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        return result

    @staticmethod
    def _to_response(reservation: Reservation) -> ReservationResponse:
        return ReservationResponse(
            reservation_id=reservation.id,
            show_id=reservation.show_id,
            user_id=reservation.user_id,
            seats=reservation.seat_labels,
            amount_paise=reservation.amount_paise,
            status=reservation.status,
        )
