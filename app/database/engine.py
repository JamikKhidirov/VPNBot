from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import config
from app.database.models import Base

engine = create_async_engine(config.DB_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.database.seed import seed_plans
    await seed_plans()


async def close_db():
    await engine.dispose()
