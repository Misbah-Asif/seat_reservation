import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user_id
from app.core.exceptions import DomainError
from app.core.logging import log_context
from app.core.metrics import (
    IDEMPOTENT_REPLAY,
    RESERVATIONS_CANCELLED,
    RESERVATIONS_CONFIRMED,
    RESERVATIONS_DECLINED,
)
from app.db.session import get_db
from app.schemas.reservation import CreateReservationRequest, ReservationResponse
from app.services.reservation_service import ReservationService

# No prefix: reservation routes live under both /shows/... and /reservations/...
router = APIRouter(tags=["reservation"])


@router.post(
    "/shows/{show_id}/reserve",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Idempotent replay: the original reservation"}},
)
async def create_reservation(
    show_id: int,
    payload: CreateReservationRequest,
    response: Response,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    # Metrics are counted here, where each outcome is final, so every 201, 200
    # replay and domain 4xx the client sees is counted exactly once.
    try:
        reservation, created = await ReservationService(db).create_reservation(
            show_id, user_id, payload
        )
    except DomainError as exc:
        log_context()["outcome"] = exc.metric_reason or exc.error
        if exc.metric_reason is not None:
            RESERVATIONS_DECLINED.labels(reason=exc.metric_reason).inc()
        raise
    log_context()["reservation_id"] = str(reservation.reservation_id)
    if created:
        log_context()["outcome"] = "confirmed"
        RESERVATIONS_CONFIRMED.inc()
    else:
        log_context()["outcome"] = IDEMPOTENT_REPLAY
        RESERVATIONS_DECLINED.labels(reason=IDEMPOTENT_REPLAY).inc()
        response.status_code = status.HTTP_200_OK
    return reservation


@router.get("/shows/{show_id}/reservations", response_model=list[ReservationResponse])
async def list_my_reservations(
    show_id: int,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[ReservationResponse]:
    """The caller's own reservations for a show (from the token, so a user can
    only ever see their own), newest first, cancelled ones included."""
    return await ReservationService(db).list_my_reservations(show_id, user_id, limit)


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    log_context()["reservation_id"] = str(reservation_id)
    try:
        reservation, cancelled_now = await ReservationService(db).cancel_reservation(
            reservation_id, user_id
        )
    except DomainError as exc:
        log_context()["outcome"] = exc.error
        raise
    log_context()["outcome"] = "cancelled" if cancelled_now else "already_cancelled"
    if cancelled_now:
        RESERVATIONS_CANCELLED.inc()
    return reservation
