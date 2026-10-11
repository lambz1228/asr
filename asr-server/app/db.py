"""异步数据库引擎与会话工厂。生产使用 asyncpg；开发默认 SQLite+aiosqlite。"""
from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .config import settings
from . import models

_is_sqlite = settings.database_url.startswith("sqlite")

# SQLite 并发参数：多人同时上传时，写事务会互相排队。
#  - timeout: aiosqlite 等待锁释放的秒数，超时前不会直接抛 "database is locked"
#  - journal_mode=WAL: 读写不再互斥（默认的 delete 模式下写会阻塞所有读）
#  - busy_timeout: 同上，驱动层的兜底等待
#  - synchronous=NORMAL: WAL 下的推荐值，兼顾安全与写入速度
_connect_args = {"timeout": 30} if _is_sqlite else {}

engine = create_async_engine(
    settings.database_url, echo=False, future=True, connect_args=_connect_args
)

if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 驱动回调
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# 轻量向前兼容迁移：create_all 只会建新表，不会给「已存在的表」补列。
# 这里只处理安全变更（新增带默认值 / 可空的列）；复杂变更请上 Alembic。
# 格式：(表名, 列名, 列定义)
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("task_packages", "param_version", "INTEGER DEFAULT 1"),
]


def _add_missing_columns(sync_conn) -> None:
    insp = inspect(sync_conn)
    for table, column, ddl in _MIGRATIONS:
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column in existing:
            continue
        sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


async def init_db() -> None:
    """建表 + 补列（生产建议改用 Alembic 迁移）。"""
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
