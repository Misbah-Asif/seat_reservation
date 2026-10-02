from sqlalchemy import insert
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
                    "seat_id": seat,
                    "seat_type": SeatTypeEnum.REGULAR,
                    "price_paise": price_paise,
                    "status": SeatStatusEnum.AVAILABLE,
                }
                for seat in seats
            ],
        )
        return show
