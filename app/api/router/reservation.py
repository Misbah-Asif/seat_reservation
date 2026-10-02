import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user_id
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
    reservation, created = await ReservationService(db).create_reservation(
        show_id, user_id, payload
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return reservation


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    return await ReservationService(db).cancel_reservation(reservation_id, user_id)
