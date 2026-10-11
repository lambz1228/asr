"""异步数据库引擎与会话工厂。生产使用 asyncpg；开发默认 SQLite+aiosqlite。"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .config import settings
from . import models

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """建表（生产建议改用 Alembic 迁移）。"""
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
