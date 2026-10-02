from typing import Annotated

from pydantic import BaseModel, Field, StrictInt, StringConstraints


class CreateShowRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    # A plain string is a regular seat at the default price (the brief's format);
    # an object can set its own type and price.
    seats: list[str] = Field(min_length=1, max_length=10_000)
    # Default price for any seat that doesn't set its own. Not stored on the show.
    price_paise: Annotated[StrictInt, Field(ge=0)]
    # None means "use settings.default_per_user_limit".
    per_user_limit: Annotated[StrictInt, Field(ge=1)] | None = None


class CreateShowResponse(BaseModel):
    id: int
    seats: list[str]
