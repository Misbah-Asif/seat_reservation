from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.session import get_db
from app.schemas.shows import CreateShowRequest, CreateShowResponse, ShowStateResponse
from app.services.show_service import ShowService

router = APIRouter(
    prefix="/shows",
    tags=["shows"],
)


@router.post(
    "",
    response_model=CreateShowResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_show(
    payload: CreateShowRequest, db: AsyncSession = Depends(get_db)
) -> CreateShowResponse:
    return await ShowService(db).create_show(payload)


# Public: anyone may view seat availability.
@router.get("/{show_id}", response_model=ShowStateResponse)
async def get_show(show_id: int, db: AsyncSession = Depends(get_db)) -> ShowStateResponse:
    return await ShowService(db).get_show_state(show_id)
