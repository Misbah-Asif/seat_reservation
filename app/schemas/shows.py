from typing import Annotated

from pydantic import BaseModel, Field, StrictInt, StringConstraints, field_validator

from app.db.models.enums import SeatStatusEnum
from app.schemas.common import MAX_DB_INT, NO_NUL, SeatLabel

# Per-seat price cap (₹1 lakh). A booking can have up to 100 seats, so
# price x 100 must still fit in reservation.amount_paise (INTEGER).
MAX_PRICE_PAISE = 10_000_000


class CreateShowRequest(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=NO_NUL)
    ]
    # Seat labels, e.g. ["A1", "A2"]. Each becomes a regular seat at price_paise.
    seats: list[SeatLabel] = Field(min_length=1, max_length=10_000)
    # Price of every seat, in integer paise.
    price_paise: Annotated[StrictInt, Field(ge=0, le=MAX_PRICE_PAISE)]
    # None means "use settings.default_per_user_limit".
    per_user_limit: Annotated[StrictInt, Field(ge=1, le=MAX_DB_INT)] | None = None

    @field_validator("seats")
    @classmethod
    def seats_unique(cls, seats: list[str]) -> list[str]:
        if len(set(seats)) != len(seats):
            raise ValueError("seat labels must be unique")
        return seats


class CreateShowResponse(BaseModel):
    id: int
    seats: list[str]


class SeatState(BaseModel):
    seat_label: str
    status: SeatStatusEnum


class SeatCounts(BaseModel):
    total_seats: int
    available: int
    held: int
    confirmed: int


class ShowStateResponse(BaseModel):
    id: int
    name: str
    per_user_limit: int
    counts: SeatCounts
    seats: list[SeatState]
