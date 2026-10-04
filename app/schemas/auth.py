from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import NO_NUL

# Same limit as reservation.user_id (varchar 100).
UserId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=NO_NUL)
]


class CreateTokenRequest(BaseModel):
    user_id: UserId


class CreateTokensRequest(BaseModel):
    # Capped so one call can't tie up the service signing tokens.
    count: int = Field(ge=1, le=10_000)


class UserToken(BaseModel):
    user_id: str
    token: str
