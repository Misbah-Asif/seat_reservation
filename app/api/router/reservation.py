from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user_id
from app.db.session import get_db
from app.schemas.reservation import CreateReservationRequest, CreateReservationResponse
from app.services.reservation_service import ReservationService

# No prefix: reservation routes live under both /shows/... and /reservations/...
router = APIRouter(tags=["reservation"])


@router.post(
    "/shows/{show_id}/reserve",
    response_model=CreateReservationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Idempotent replay: the original reservation"}},
)
async def create_reservation(
    show_id: int,
    payload: CreateReservationRequest,
    response: Response,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> CreateReservationResponse:
    reservation, created = await ReservationService(db).create_reservation(
        show_id, user_id, payload
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return reservation
