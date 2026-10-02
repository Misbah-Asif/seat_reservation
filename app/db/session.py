from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
