"""过期导出文件清理（方案 §6.2：导出包留存 7 天后自动删除）。

触发点（三处，互为兜底）：
1. 服务启动时（main.py lifespan）—— 兜住长期无人导出的情况
2. 每次导出完成后 —— 顺手清一次，避免越积越多
3. 管理员手动 `POST /api/admin/export/cleanup`

留存天数由 EXPORT_TTL_DAYS 控制（默认 7，置 0 关闭清理）。
清理两类对象：
- 台账（ExportJob）中已完成且超过留存的导出包 → 删文件 + 状态置 `expired`
- `exports/` 下不在台账中的孤儿文件（如台账已丢失）且超过留存的 → 直接删
"""
import time
from datetime import timedelta

from sqlalchemy import select

from . import models
from .config import settings
from .storage import storage

EXPORT_PREFIX = "exports/"


async def purge_expired_exports(db, ttl_days: int | None = None) -> dict:
    """删除超过留存期的导出文件，返回清理统计。幂等，可重复调用。"""
    ttl = settings.export_ttl_days if ttl_days is None else ttl_days
    if ttl <= 0:
        return {
            "enabled": False,
            "ttlDays": ttl,
            "expiredJobs": 0,
            "deletedFiles": 0,
            "orphans": 0,
        }

    cutoff_ts = time.time() - ttl * 86400
    cutoff_dt = models.utcnow() - timedelta(days=ttl)

    # 1) 已完成且超期的导出任务 → 删文件 + 标记 expired（保留记录便于追溯）
    rows = await db.execute(
        select(models.ExportJob).where(
            models.ExportJob.status == "done",
            models.ExportJob.finished_at.is_not(None),
            models.ExportJob.finished_at < cutoff_dt,
        )
    )
    expired_jobs = list(rows.scalars().all())
    deleted = 0
    for job in expired_jobs:
        if job.key:
            try:
                if await storage.delete(job.key):
                    deleted += 1
            except Exception:
                pass  # 删失败留给下一轮（文件会落进孤儿分支重试）
        job.status = "expired"
        job.key = None

    # 2) exports/ 下的孤儿文件（台账无记录，如记录被清掉）且超期 → 删
    try:
        objects = await storage.list(EXPORT_PREFIX)
    except Exception:
        objects = []
    known = {
        k
        for (k,) in (
            await db.execute(select(models.ExportJob.key).where(models.ExportJob.key.is_not(None)))
        ).all()
        if k
    }
    orphans = 0
    for key, mtime in objects:
        if key in known or (mtime and mtime > cutoff_ts):
            continue
        try:
            if await storage.delete(key):
                orphans += 1
        except Exception:
            pass

    await db.commit()
    return {
        "enabled": True,
        "ttlDays": ttl,
        "cutoff": cutoff_dt.isoformat(),
        "expiredJobs": len(expired_jobs),
        "deletedFiles": deleted,
        "orphans": orphans,
    }
