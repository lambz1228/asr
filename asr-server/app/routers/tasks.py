from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update

from .. import models
from ..deps import get_current_user, get_db, record_audit
from ..responses import ok
from ..stats import summarize

router = APIRouter()


@router.get("/progress")
async def my_progress(user=Depends(get_current_user), db=Depends(get_db)):
    """采集员个人进度（方案 §9.1）：总任务 / 各状态计数 / 完成率。"""
    rows = await db.execute(
        select(models.TaskAssignment.status, func.count())
        .where(models.TaskAssignment.assignee == user["uid"])
        .group_by(models.TaskAssignment.status)
    )
    counts = {st: n for st, n in rows.all()}
    return ok(summarize(counts))


@router.get("/tasks")
async def list_tasks(
    status: str | None = None,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """我的任务。status 可选筛选；已退回的任务附带最近一次退回原因（供采集员针对性重录）。

    录音页按 deque 顺序上下条切换，因此额外返回 textId 与所属任务包名（pkgName），
    供界面展示「当前任务包」「编号」等信息（对齐参考版式）。
    """
    q = (
        select(models.TaskAssignment, models.TextItem)
        .join(models.TextItem, models.TaskAssignment.text_id == models.TextItem.text_id)
        .where(models.TaskAssignment.assignee == user["uid"])
    )
    if status:
        q = q.where(models.TaskAssignment.status == status)
    rows = await db.execute(q.order_by(models.TaskAssignment.id))
    pairs = rows.all()

    # 批量取任务包名，避免逐条查询（N+1）
    pkg_ids = {asg.pkg_id for asg, _ in pairs}
    pkg_names: dict[str, str] = {}
    if pkg_ids:
        pk = await db.execute(
            select(models.TaskPackage.pkg_id, models.TaskPackage.name).where(
                models.TaskPackage.pkg_id.in_(pkg_ids)
            )
        )
        pkg_names = {pid: name for pid, name in pk.all()}

    # 批量取「最近一次退回原因」，同样避免 N+1：
    # 原来每条 rejected 任务都要单独查一次 ReviewLog，退回件一多（几十上百条）
    # 就是几十上百次往返，首屏明显变慢。这里一次查完再在内存里取每个任务的最新一条。
    rejected_ids = [asg.assignment_id for asg, _ in pairs if asg.status == "rejected"]
    reject_reasons: dict[str, str | None] = {}
    if rejected_ids:
        rr = await db.execute(
            select(
                models.Recording.assignment_id,
                models.ReviewLog.reason,
                models.ReviewLog.id,
            )
            .join(
                models.ReviewLog,
                models.ReviewLog.recording_id == models.Recording.recording_id,
            )
            .where(
                models.Recording.assignment_id.in_(rejected_ids),
                models.ReviewLog.action == "reject",
            )
            # 倒序：每个任务第一次出现的即最新一条
            .order_by(models.ReviewLog.id.desc())
        )
        for aid, reason, _log_id in rr.all():
            if aid not in reject_reasons:
                reject_reasons[aid] = reason

    tasks = []
    for asg, text in pairs:
        reason = reject_reasons.get(asg.assignment_id) if asg.status == "rejected" else None
        tasks.append(
            {
                "id": asg.assignment_id,
                "textId": text.text_id,
                "text": text.text,
                "pkgId": asg.pkg_id,
                "pkgName": pkg_names.get(asg.pkg_id, ""),
                "status": asg.status,
                "version": asg.version,
                "rejectReason": reason,
            }
        )
    return ok({"list": tasks})


@router.get("/tasks/pool")
async def list_pool(user=Depends(get_current_user), db=Depends(get_db)):
    """公共池：未分配的 pending 任务，任何采集员都可领取（对应导入时 assignee 留空）。"""
    rows = await db.execute(
        select(models.TaskAssignment, models.TextItem)
        .join(models.TextItem, models.TaskAssignment.text_id == models.TextItem.text_id)
        .where(
            models.TaskAssignment.assignee.is_(None),
            models.TaskAssignment.status == "pending",
        )
        .order_by(models.TaskAssignment.id)
    )
    tasks = [
        {"id": asg.assignment_id, "text": text.text, "status": asg.status}
        for asg, text in rows.all()
    ]
    return ok({"list": tasks})


@router.post("/tasks/{task_id}/claim")
async def claim_task(task_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    """抢领任务（并发安全）。

    用「带条件的原子 UPDATE」而非「先 SELECT 判断、再赋值」：
    后者在多人同时抢领时，多个请求会同时读到 status == 'pending'，
    于是都判定自己领到了 —— 实测 20 人并发抢同一个任务，会有十几个人
    收到 claimed=True，而库里的 assignee 被反复覆盖，最终只有一个赢家。
    调用方按 claimed=True 去录，实际任务并不属于他。

    这里把状态判断下推给数据库：WHERE status='pending' 保证只有一行被更新，
    再按 rowcount 判断是否真的抢到。
    """
    res = await db.execute(
        update(models.TaskAssignment)
        .where(
            models.TaskAssignment.assignment_id == task_id,
            models.TaskAssignment.status == "pending",
        )
        .values(status="claimed", assignee=user["uid"])
    )
    if res.rowcount == 1:
        record_audit(db, user["uid"], "collector", "claim", "assignment", task_id)
        await db.commit()
        return ok({"status": "claimed", "claimed": True})

    # 没抢到：可能是任务不存在，也可能是已被别人领走
    await db.rollback()
    asg = await db.scalar(
        select(models.TaskAssignment).where(
            models.TaskAssignment.assignment_id == task_id
        )
    )
    if not asg:
        return {"code": 1, "message": "任务不存在", "data": None}
    return ok({"status": asg.status, "claimed": False})
