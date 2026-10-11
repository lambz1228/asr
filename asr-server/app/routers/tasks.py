from fastapi import APIRouter, Depends
from sqlalchemy import select

from .. import models
from ..deps import get_current_user, get_db, record_audit
from ..responses import ok

router = APIRouter()


@router.get("/tasks")
async def list_tasks(user=Depends(get_current_user), db=Depends(get_db)):
    rows = await db.execute(
        select(models.TaskAssignment, models.TextItem)
        .join(models.TextItem, models.TaskAssignment.text_id == models.TextItem.text_id)
        .where(models.TaskAssignment.assignee == user["uid"])
        .order_by(models.TaskAssignment.id)
    )
    tasks = [
        {"id": asg.assignment_id, "text": text.text, "status": asg.status}
        for asg, text in rows.all()
    ]
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
    asg = await db.scalar(
        select(models.TaskAssignment).where(
            models.TaskAssignment.assignment_id == task_id
        )
    )
    if not asg:
        return {"code": 1, "message": "任务不存在", "data": None}
    # 抢领模式乐观锁：仅当仍处于 pending 时原子领取
    if asg.status != "pending":
        return ok({"status": asg.status, "claimed": False})
    asg.status = "claimed"
    asg.assignee = user["uid"]
    record_audit(db, user["uid"], "collector", "claim", "assignment", task_id)
    await db.commit()
    return ok({"status": "claimed", "claimed": True})
