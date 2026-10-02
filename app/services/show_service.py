from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ShowNotFound
from app.db.models.enums import SeatStatusEnum
from app.repositories.show_repository import ShowRepository
from app.schemas.shows import (
    CreateShowRequest,
    CreateShowResponse,
    SeatCounts,
    SeatState,
    ShowStateResponse,
)


class ShowService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.shows = ShowRepository(db)

    async def create_show(self, payload: CreateShowRequest) -> CreateShowResponse:
        # Show and all its seats commit in one transaction: never a show with half its seats.
        seats = payload.seats
        price_paise = payload.price_paise
        show = await self.shows.create_with_seats(
            name=payload.name,
            per_user_limit=(
                settings.default_per_user_limit
                if payload.per_user_limit is None
                else payload.per_user_limit
            ),
            seats=seats,
            price_paise=price_paise
        )
        await self.db.commit()

        # total = len(seats)
        return CreateShowResponse(
            id=show.id,
            seats=seats,
        )

    async def get_show_state(self, show_id: int) -> ShowStateResponse:
        show = await self.shows.get(show_id)
        if show is None:
            raise ShowNotFound(show_id=show_id)

        seats = await self.shows.get_seat_states(show_id)
        # Counts come from the same rows as the seat list, so they always agree
        # and available + held + confirmed == total_seats by construction.
        by_status = Counter(status for _, status in seats)
        return ShowStateResponse(
            id=show.id,
            name=show.name,
            per_user_limit=show.per_user_limit,
            counts=SeatCounts(
                total_seats=len(seats),
                available=by_status[SeatStatusEnum.AVAILABLE],
                held=by_status[SeatStatusEnum.HELD],
                confirmed=by_status[SeatStatusEnum.CONFIRMED],
            ),
            seats=[SeatState(seat_label=label, status=status) for label, status in seats],
        )
