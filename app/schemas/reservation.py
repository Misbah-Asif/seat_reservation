import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.db.models.enums import ReservationStatusEnum

SeatLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class CreateReservationRequest(BaseModel):
    # No user_id field: identity comes from the auth token only. An extra
    # "user_id" in the body is ignored, so it can't be spoofed.
    seats: list[SeatLabel] = Field(min_length=1, max_length=100)
    idempotency_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]

    @field_validator("seats")
    @classmethod
    def seats_unique(cls, seats: list[str]) -> list[str]:
        if len(set(seats)) != len(seats):
            raise ValueError("seat labels must be unique")
        return seats


class ReservationResponse(BaseModel):
    reservation_id: uuid.UUID
    show_id: int
    user_id: str
    seats: list[str]
    amount_paise: int
    status: ReservationStatusEnum
