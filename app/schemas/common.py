from typing import Annotated

from fastapi import Path
from pydantic import StringConstraints

# Postgres INTEGER max. Ids and amounts above it would be rejected by the
# database (a 500); validating here turns them into a clean 422 instead.
MAX_DB_INT = 2_147_483_647

# Postgres text can't store a NUL byte (\x00): it would reach the database and
# fail as a 500. Every free-text field uses this pattern to reject it as a 422.
NO_NUL = r"^[^\x00]*$"

# Matches seat.seat_label VARCHAR(100).
SeatLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=NO_NUL)
]

# Path parameter for show ids.
ShowId = Annotated[int, Path(ge=1, le=MAX_DB_INT)]
