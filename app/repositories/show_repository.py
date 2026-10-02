from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import SeatStatusEnum, SeatTypeEnum
from app.db.models.seat import Seat
from app.db.models.show import Show


class ShowRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_with_seats(self, name: str, per_user_limit: int, seats: list[str], price_paise: int) -> Show:
        show = Show(name=name, per_user_limit=per_user_limit)
        self.db.add(show)
        await self.db.flush()  # assigns show.id

        # One multi-row INSERT for all seats instead of N ORM objects.
        await self.db.execute(
            insert(Seat),
            [
                {
                    "show_id": show.id,
                    "seat_label": seat,
                    "seat_type": SeatTypeEnum.REGULAR,
                    "price_paise": price_paise,
                    "status": SeatStatusEnum.AVAILABLE,
                }
                for seat in seats
            ],
        )
        return show

    async def get(self, show_id: int) -> Show | None:
        return await self.db.get(Show, show_id)

    async def get_seat_states(self, show_id: int) -> list[tuple[str, SeatStatusEnum]]:
        """(label, status) for every seat, in creation order.

        A single SELECT, so all rows come from one snapshot: the counts built
        from this list always add up to the total, even mid-burst.
        """
        result = await self.db.execute(
            select(Seat.seat_label, Seat.status).where(Seat.show_id == show_id).order_by(Seat.id)
        )
        return [(label, status) for label, status in result]
