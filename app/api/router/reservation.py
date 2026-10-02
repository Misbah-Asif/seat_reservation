from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.reservation import CreateReservationRequest, CreateReservationResponse
from app.services.reservation_service import ReservationService

router = APIRouter(
    prefix="/reservation",
    tags=["reservation"],
)


@router.post("", response_model=CreateReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: CreateReservationRequest, db: AsyncSession = Depends(get_db)
) -> CreateReservationResponse:
    return await ReservationService(db).create_reservation(payload)
