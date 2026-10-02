from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.show_repository import ShowRepository
from app.schemas.shows import CreateShowRequest, CreateShowResponse


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
