from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.shows import CreateShowRequest, CreateShowResponse
from app.services.show_service import ShowService

router = APIRouter(
    prefix="/shows",
    tags=["shows"],
)


# TODO: admin auth.
@router.post("", response_model=CreateShowResponse, status_code=status.HTTP_201_CREATED)
async def create_show(
    payload: CreateShowRequest, db: AsyncSession = Depends(get_db)
) -> CreateShowResponse:
    return await ShowService(db).create_show(payload)
