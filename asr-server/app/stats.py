"""进度统计口径（方案 §9.1）：采集员个人进度与管理端全局进度共用同一套算法。

任务状态机：pending(待领取) → claimed(待录制) → uploaded(待审核) → approved(已通过) / rejected(已退回)

口径说明：
- 完成率 completionRate = 已通过 / 总任务数（审核通过才算真正完成）
- pending = pending + claimed（尚未上传录音）
- recorded = uploaded + approved + rejected（已上传过，含待审与退回）
"""

# 视为「未录制」的状态
PENDING_STATUSES = ("pending", "claimed")

STATUS_LABELS = {
    "pending": "待领取",
    "claimed": "待录制",
    "uploaded": "待审核",
    "approved": "已通过",
    "rejected": "已退回",
}


def summarize(counts: dict) -> dict:
    """把 {status: 条数} 汇总为带完成率的进度对象。"""
    total = sum(counts.values())
    approved = counts.get("approved", 0)
    uploaded = counts.get("uploaded", 0)
    rejected = counts.get("rejected", 0)
    pending = sum(counts.get(s, 0) for s in PENDING_STATUSES)
    return {
        "total": total,
        "pending": pending,
        "uploaded": uploaded,
        "approved": approved,
        "rejected": rejected,
        "recorded": uploaded + approved + rejected,
        # 保留 4 位小数，前端按百分比展示
        "completionRate": round(approved / total, 4) if total else 0.0,
    }
