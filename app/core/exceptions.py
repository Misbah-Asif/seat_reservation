from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """An expected business outcome (seat taken, show missing, ...), not a bug.

    Always maps to a 4xx with a stable `error` code, never a 500. The code is
    mapped to a metric label via `metric_reason`."""

    status_code = 400
    error = "bad_request"
    # Label for reservations_declined_total when a reserve request ends with
    # this error. None: not counted as a reservation decline.
    metric_reason: str | None = None

    def __init__(self, **details: Any):
        super().__init__(self.error)
        self.details = details


class ShowNotFound(DomainError):
    status_code = 404
    error = "show_not_found"
    metric_reason = "show_not_found"


class ReservationNotFound(DomainError):
    """Also returned when the reservation belongs to someone else, so a
    stranger can't tell whether a booking exists."""

    status_code = 404
    error = "reservation_not_found"


class SeatsNotFound(DomainError):
    status_code = 404
    error = "seats_not_found"
    metric_reason = "seats_not_found"


class SeatsUnavailable(DomainError):
    status_code = 409
    error = "seats_unavailable"
    metric_reason = "seat_taken"


class PerUserLimitExceeded(DomainError):
    status_code = 409
    error = "per_user_limit_exceeded"
    metric_reason = "per_user_limit"


class IdempotencyKeyReused(DomainError):
    """Same idempotency key, different request body."""

    status_code = 409
    error = "idempotency_key_reused"
    metric_reason = "idempotency_key_reused"


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.error, **exc.details})
