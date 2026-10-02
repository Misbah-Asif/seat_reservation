import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.metrics import SEATS_AVAILABLE, SEATS_CONFIRMED, SEATS_HELD
from app.db.models.enums import SeatStatusEnum
from app.db.session import probe_engine
from app.repositories.show_repository import ShowRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])

_GAUGES = {
    SeatStatusEnum.AVAILABLE: SEATS_AVAILABLE,
    SeatStatusEnum.HELD: SEATS_HELD,
    SeatStatusEnum.CONFIRMED: SEATS_CONFIRMED,
}
# Two scrapes at once must not interleave clearing and setting the gauges.
_scrape_lock = asyncio.Lock()


async def _read_seat_counts() -> dict[int, dict[SeatStatusEnum, int]] | None:
    """Seat counts per show from the database, or None if it can't be read."""
    try:
        async with asyncio.timeout(settings.ready_timeout_seconds):
            async with AsyncSession(probe_engine) as db:
                rows = await ShowRepository(db).count_seats_by_show_and_status()
    except Exception as exc:
        logger.warning("metrics: seat counts unavailable: %s: %s", type(exc).__name__, exc)
        return None
    counts: dict[int, dict[SeatStatusEnum, int]] = defaultdict(dict)
    for show_id, status, count in rows:
        counts[show_id][status] = count
    return counts


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus text format. Public, so the burst can be watched live."""
    counts = await _read_seat_counts()
    async with _scrape_lock:
        # Rebuilt from scratch each time: a stale value is worse than none.
        # If the DB is unreachable the seat gauges are simply absent, and the
        # counters are still returned.
        for gauge in _GAUGES.values():
            gauge.clear()
        for show_id, by_status in (counts or {}).items():
            for status, gauge in _GAUGES.items():
                gauge.labels(show_id=str(show_id)).set(by_status.get(status, 0))
        body = generate_latest()
    return Response(body, media_type=CONTENT_TYPE_LATEST)
