import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.db.session import probe_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Process is up. Never touches the database."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> JSONResponse:
    """Can serve traffic: the database answers. Fails closed with 503.

    Uses probe_engine (its own connection, not the request pool), so a busy
    pool during a burst doesn't make this report "not ready"."""
    try:
        async with asyncio.timeout(settings.ready_timeout_seconds):
            async with probe_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:  # any failure (refused, timeout, auth) means not ready
        logger.warning("readiness check failed: %s: %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "database": "unreachable"}
        )
    return JSONResponse(status_code=200, content={"status": "ok", "database": "ok"})
