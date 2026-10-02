from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """An expected business outcome (seat taken, show missing, ...), not a bug.

    Always maps to a 4xx with a stable `error` code, never a 500. The code is
    also what the declined-by-reason metric will be labelled with later."""

    status_code = 400
    error = "bad_request"

    def __init__(self, **details: Any):
        super().__init__(self.error)
        self.details = details


class ShowNotFound(DomainError):
    status_code = 404
    error = "show_not_found"


class SeatsNotFound(DomainError):
    status_code = 404
    error = "seats_not_found"


class SeatsUnavailable(DomainError):
    status_code = 409
    error = "seats_unavailable"


class PerUserLimitExceeded(DomainError):
    status_code = 409
    error = "per_user_limit_exceeded"


class IdempotencyKeyReused(DomainError):
    """Same idempotency key, different request body."""

    status_code = 409
    error = "idempotency_key_reused"


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.error, **exc.details})
