from typing import Annotated

from pydantic import BaseModel, Field, StrictInt, StringConstraints, model_validator

from app.db.models.enums import SeatStatusEnum, SeatTypeEnum

# SeatLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# StrictInt rejects 250.0 and "25000": money is integer paise only.
Paise = Annotated[StrictInt, Field(ge=0)]


# class SeatIn(BaseModel):
#     seat_id: SeatLabel
#     seat_type: SeatTypeEnum = SeatTypeEnum.REGULAR
#     # Falls back to the show-level default price when omitted.
#     price_paise: Paise | None = None


class CreateShowRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    # A plain string is a regular seat at the default price (the brief's format);
    # an object can set its own type and price.
    seats: list[str] = Field(min_length=1, max_length=10_000)
    # Default price for any seat that doesn't set its own. Not stored on the show.
    price_paise: Paise
    # None means "use settings.default_per_user_limit".
    per_user_limit: Annotated[StrictInt, Field(ge=1)] | None = None


class SeatOut(BaseModel):
    seat_id: str
    status: SeatStatusEnum


class SeatCounts(BaseModel):
    total_seats: int
    available: int
    held: int
    confirmed: int


class CreateShowResponse(BaseModel):
    id: int
    seats: list[str]
