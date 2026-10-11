"""开发态演示数据播种：无数据时创建示例用户、任务包与分配给 demo 用户的任务。"""
from sqlalchemy import select

from . import models

DEMO_USER = "u_demo"
DEMO_TEXTS = [
    "今天天气真好，我们一起去公园散步吧。",
    "请朗读这一段新闻：本地气温将明显下降。",
    "你好，很高兴认识你，这是一段测试语音。",
]


async def seed_demo_data(db) -> None:
    if await db.scalar(select(models.User).limit(1)):
        return
    db.add(models.User(user_id=DEMO_USER, role="collector"))
    # 管理端演示账号：dev 登录传 role=admin 时取用
    db.add(models.User(user_id="u_admin", role="admin"))
    pkg = models.TaskPackage(
        pkg_id="pkg_demo",
        name="示例任务包",
        params={"sample_rate": 16000, "channels": 1, "format": "aac"},
        created_by="admin",
    )
    db.add(pkg)
    await db.flush()
    for i, text in enumerate(DEMO_TEXTS, 1):
        tid = f"t{i}"
        db.add(
            models.TextItem(
                text_id=tid, pkg_id=pkg.pkg_id, text=text, text_version=1
            )
        )
        db.add(
            models.TaskAssignment(
                assignment_id=f"a{i}",
                pkg_id=pkg.pkg_id,
                text_id=tid,
                assignee=DEMO_USER,
                status="pending",
            )
        )
    await db.commit()
