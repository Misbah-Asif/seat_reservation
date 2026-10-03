import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import RequestLoggingMiddleware, setup_logging

setup_logging(settings.log_level)

from app.api.router import auth, health, metrics, reservation, shows  # noqa: E402
from app.core.exceptions import DomainError, domain_error_handler  # noqa: E402
from app.core.metrics import HttpMetricsMiddleware  # noqa: E402
from app.db.session import engine, probe_engine  # noqa: E402

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "app started",
        extra={
            "db_pool_size": settings.db_pool_size,
            "db_max_overflow": settings.db_max_overflow,
            "token_ttl_seconds": settings.token_ttl_seconds,
            "default_per_user_limit": settings.default_per_user_limit,
        },
    )
    yield
    await engine.dispose()
    await probe_engine.dispose()
    logger.info("app stopped")


app = FastAPI(title="Seat Reservation", lifespan=lifespan)
# Added last = outermost: the request id exists before anything else runs.
app.add_middleware(HttpMetricsMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(shows.router)
app.include_router(reservation.router)
app.add_exception_handler(DomainError, domain_error_handler)

# if __name__ == "__main__":
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
