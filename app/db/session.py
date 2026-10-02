from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

# DATABASE_URI must use the asyncpg driver: postgresql+asyncpg://...
engine = create_async_engine(
    settings.database_uri,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# For /health/ready and /metrics only, kept apart from the request pool on
# purpose: during a burst every pooled connection can be busy, and a check
# queued behind them would report "not ready" (or time out) while the database
# is fine. NullPool opens a fresh connection per use, so observability never
# competes with bookings for a connection.
probe_engine = create_async_engine(
    settings.database_uri,
    poolclass=NullPool,
    connect_args={"timeout": settings.ready_timeout_seconds},
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
