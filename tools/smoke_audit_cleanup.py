"""烟测：审计日志查询（方案 §9.1）+ 导出文件过期清理（方案 §6.2）。

覆盖：
1. 审计日志
   - GET /api/admin/audit-logs 返回操作记录（此前 AuditLog 只写不查）
   - 字段完整（operatorId/operatorRole/action/targetType/targetId/detail/createdAt）
   - 按 action / operator 过滤、分页 offset+limit
   - actions 去重列表（供前端渲染筛选项）
   - 权限：admin 可读；reviewer 与 collector 均 403
2. 导出清理
   - GET /api/admin/export/jobs 可用（路由须排在 /export/{job_id} 之前，否则被吞成 404）
   - POST /api/admin/export/cleanup 删除超期导出包、标记 ExportJob=expired、清掉孤儿文件
   - 未超期的导出包 / 新孤儿文件不被误删
   - 清理动作本身写入审计日志
   - EXPORT_TTL_DAYS=0 时关闭清理

使用独立临时库（_smoke_audit.db）与临时存储目录（_smoke_data），不污染开发库 asr.db。
运行：python tools/smoke_audit_cleanup.py
"""
import asyncio
import os
import sys
import time
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "asr-server")
os.chdir(SERVER)
sys.path.insert(0, SERVER)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_smoke_audit.db"
os.environ["LOCAL_STORAGE_PATH"] = "./_smoke_data"
os.environ["ENV"] = "dev"
os.environ["DEV_MOCK_LOGIN"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["FFMPEG_ENABLED"] = "false"
os.environ["EXPORT_TTL_DAYS"] = "7"

# 每次从干净库开始：残留的 export_jobs 会让清理断言误判。
# 注意：WAL 模式下 SQLite 还会生成 -wal / -shm 侧车文件，必须一并删除，
# 否则残留的 WAL 会把上一次的写入带回来，表现为难以复现的假失败。
for _suf in ("", "-wal", "-shm", "-journal"):
    _p = os.path.join(SERVER, "_smoke_audit.db" + _suf)
    if os.path.exists(_p):
        os.remove(_p)

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from app import models  # noqa: E402
from app.cleanup import purge_expired_exports  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.storage import storage  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("  | " + extra if extra else ""))


def backdate(key: str, days: float) -> None:
    """把存储对象的 mtime 往前拨，模拟「已过期」。"""
    path = storage._path(key)
    ts = time.time() - days * 86400
    os.utime(path, (ts, ts))


async def seed_export_jobs() -> None:
    """造 4 个导出包：过期 1、未过期 1、过期孤儿 1、新孤儿 1。"""
    await storage.save("exports/job_old.zip", b"old-zip")
    await storage.save("exports/job_new.zip", b"new-zip")
    backdate("exports/job_old.zip", 8)
    async with SessionLocal() as db:
        db.add_all(
            [
                models.ExportJob(
                    job_id="job_old",
                    status="done",
                    total=5,
                    key="exports/job_old.zip",
                    created_at=models.utcnow() - timedelta(days=8),
                    finished_at=models.utcnow() - timedelta(days=8),
                ),
                models.ExportJob(
                    job_id="job_new",
                    status="done",
                    total=1,
                    key="exports/job_new.zip",
                    created_at=models.utcnow(),
                    finished_at=models.utcnow(),
                ),
            ]
        )
        await db.commit()
    # 孤儿：台账里没有的文件
    await storage.save("exports/orphan_old.zip", b"orphan")
    backdate("exports/orphan_old.zip", 9)
    await storage.save("exports/orphan_fresh.zip", b"orphan-fresh")


async def job_states() -> dict:
    async with SessionLocal() as db:
        out = {}
        for jid in ("job_old", "job_new"):
            job = await db.get(models.ExportJob, jid)
            out[jid] = (job.status, job.key) if job else None
        return out


def exists(key: str) -> bool:
    return os.path.exists(storage._path(key))


async def purge_with_ttl(ttl: int) -> dict:
    async with SessionLocal() as db:
        return await purge_expired_exports(db, ttl_days=ttl)


with TestClient(app) as c:

    def login(role=None):
        payload = {"code": "smoke_audit_" + (role or "default")}
        if role:
            payload["role"] = role
        b = c.post("/api/auth/wx-login", json=payload).json()
        assert b.get("code") == 0, b
        return b["data"]["token"]

    def H(t):
        return {"Authorization": "Bearer " + t}

    admin_t = login("admin")
    col_t = login()

    print("[审计日志] 造记录：同意书 / 导入 / 上传+审核 / 角色调整")
    c.post("/api/auth/consent", json={"type": "voice_sensitive"}, headers=H(col_t))
    c.post(
        "/api/admin/packages/import",
        json={
            "pkgId": "pkg_audit_smoke",
            "name": "冒烟-审计日志",
            "texts": [{"text": "审计用文本一"}, {"text": "审计用文本二"}],
            "assignees": ["u_demo"],
        },
        headers=H(admin_t),
    )
    c.post(
        "/api/tasks/a1/upload",
        files={"file": ("a.aac", b"\x00\x01\x02", "audio/aac")},
        data={"textId": "t1", "uploadId": "smoke_audit_up1"},
        headers=H(col_t),
    )
    audios = c.get("/api/admin/audios", headers=H(admin_t)).json()["data"]["list"]
    c.post(
        f"/api/admin/audios/{audios[0]['recordingId']}/review",
        json={"action": "reject", "reason": "噪声偏大"},
        headers=H(admin_t),
    )
    c.post("/api/admin/users/u_demo/role", json={"role": "collector"}, headers=H(admin_t))

    print("[审计日志] 列表与字段")
    r = c.get("/api/admin/audit-logs", headers=H(admin_t))
    body = r.json()
    check("管理员可读审计日志", r.status_code == 200 and body.get("code") == 0, str(r.status_code))
    data = body["data"]
    check("返回 total / limit / offset / actions", all(
        k in data for k in ("total", "limit", "offset", "actions", "list")
    ), str(list(data.keys())))
    check("记录数 ≥ 5（同意/导入/上传/审核/改角色）", data["total"] >= 5, str(data["total"]))

    first = data["list"][0]
    need = ["id", "operatorId", "operatorRole", "action", "targetType",
            "targetId", "detail", "createdAt"]
    check("日志条目字段完整", all(k in first for k in need), str(sorted(first.keys())))
    check("倒序：最新一条是改角色 set_role", first["action"] == "set_role", str(first["action"]))
    check("条目含操作人角色", first["operatorRole"] == "admin", str(first["operatorRole"]))
    check("set_role 详情记录 from/to",
          first["detail"].get("to") == "collector", str(first["detail"]))

    got = {x["action"] for x in data["list"]}
    for a in ("consent", "import_package", "upload", "review", "set_role"):
        check(f"日志含 {a}", a in got, str(sorted(got)))
    check("actions 去重列表供前端筛选项",
          set(data["actions"]) >= {"consent", "import_package", "review", "set_role"},
          str(data["actions"]))

    print("[审计日志] 过滤与分页")
    fr = c.get("/api/admin/audit-logs?action=review", headers=H(admin_t)).json()["data"]
    check("按 action=review 过滤：全部命中", fr["list"] and all(
        x["action"] == "review" for x in fr["list"]), str([x["action"] for x in fr["list"]]))
    check("按 action 过滤后 total 变小", fr["total"] < data["total"], f"{fr['total']} < {data['total']}")
    check("过滤时 actions 仍返回全量（便于切换筛选）",
          len(fr["actions"]) == len(data["actions"]), str(fr["actions"]))

    op = c.get("/api/admin/audit-logs?operator=u_admin", headers=H(admin_t)).json()["data"]
    check("按 operator=u_admin 过滤：全部为 u_admin",
          op["list"] and all(x["operatorId"] == "u_admin" for x in op["list"]),
          str({x["operatorId"] for x in op["list"]}))

    p1 = c.get("/api/admin/audit-logs?limit=2&offset=0", headers=H(admin_t)).json()["data"]
    p2 = c.get("/api/admin/audit-logs?limit=2&offset=2", headers=H(admin_t)).json()["data"]
    check("分页 limit=2 生效", len(p1["list"]) == 2, str(len(p1["list"])))
    check("分页 total 恒定", p1["total"] == data["total"] == p2["total"], str(p1["total"]))
    check("分页不重叠", not ({x["id"] for x in p1["list"]} & {x["id"] for x in p2["list"]}),
          f"{[x['id'] for x in p1['list']]} vs {[x['id'] for x in p2['list']]}")
    tf = c.get("/api/admin/audit-logs?targetType=user", headers=H(admin_t)).json()["data"]
    check("按 targetType=user 过滤生效",
          all(x["targetType"] == "user" for x in tf["list"]) and tf["total"] >= 2, str(tf["total"]))

    print("[审计日志] 权限边界")
    c.post("/api/admin/users/u_demo/role", json={"role": "reviewer"}, headers=H(admin_t))
    rev_t = login()
    check("reviewer 读审计日志被拒 403（含角色调整等敏感记录）",
          c.get("/api/admin/audit-logs", headers=H(rev_t)).status_code == 403)
    c.post("/api/admin/users/u_demo/role", json={"role": "collector"}, headers=H(admin_t))
    col_t = login()
    check("采集员读审计日志被拒 403",
          c.get("/api/admin/audit-logs", headers=H(col_t)).status_code == 403)

    print("[导出清理] 准备 4 个导出包（过期 / 未过期 / 过期孤儿 / 新孤儿）")
    asyncio.run(seed_export_jobs())
    check("过期导出包文件已就位", exists("exports/job_old.zip"))

    r = c.get("/api/admin/export/jobs", headers=H(admin_t))
    check("导出任务列表可用（路由未被 /export/{job_id} 吞掉）",
          r.status_code == 200 and "list" in (r.json().get("data") or {}), str(r.status_code))
    jd = r.json()["data"]
    check("列表返回 ttlDays=7", jd["ttlDays"] == 7, str(jd["ttlDays"]))
    old_item = next((x for x in jd["list"] if x["jobId"] == "job_old"), None)
    check("已完成任务带留存到期时间 expiresAt",
          old_item is not None and bool(old_item["expiresAt"]), str(old_item))
    c.post("/api/admin/users/u_demo/role", json={"role": "reviewer"}, headers=H(admin_t))
    rev2 = login()
    check("reviewer 可读导出任务列表",
          c.get("/api/admin/export/jobs", headers=H(rev2)).status_code == 200)
    check("reviewer 执行清理被拒 403（清理限管理员）",
          c.post("/api/admin/export/cleanup", headers=H(rev2)).status_code == 403)
    c.post("/api/admin/users/u_demo/role", json={"role": "collector"}, headers=H(admin_t))
    col2 = login()
    check("采集员读导出任务列表被拒 403",
          c.get("/api/admin/export/jobs", headers=H(col2)).status_code == 403)

    print("[导出清理] 管理员触发清理")
    cr = c.post("/api/admin/export/cleanup", headers=H(admin_t))
    check("清理接口返回成功", cr.status_code == 200 and cr.json().get("code") == 0, str(cr.status_code))
    stats = cr.json()["data"]
    check("统计含 ttlDays / expiredJobs / deletedFiles / orphans",
          all(k in stats for k in ("ttlDays", "expiredJobs", "deletedFiles", "orphans")), str(stats))
    check("过期任务被清理 1 个", stats["expiredJobs"] == 1, str(stats))
    check("删除文件数 ≥ 1（过期包）", stats["deletedFiles"] >= 1, str(stats))
    check("孤儿文件被清理 1 个", stats["orphans"] == 1, str(stats))

    check("过期导出包文件已删除", not exists("exports/job_old.zip"))
    check("过期孤儿文件已删除", not exists("exports/orphan_old.zip"))
    check("未过期导出包保留", exists("exports/job_new.zip"))
    check("未过期孤儿文件保留", exists("exports/orphan_fresh.zip"))

    st = asyncio.run(job_states())
    check("过期任务状态置 expired", st["job_old"][0] == "expired", str(st["job_old"]))
    check("过期任务清空 key（不再暴露下载）", st["job_old"][1] is None, str(st["job_old"]))
    check("未过期任务状态仍为 done", st["job_new"][0] == "done", str(st["job_new"]))

    print("[导出清理] 幂等 + 清理动作入审计")
    stats2 = c.post("/api/admin/export/cleanup", headers=H(admin_t)).json()["data"]
    check("再次清理无对象可删（幂等）",
          stats2["expiredJobs"] == 0 and stats2["deletedFiles"] == 0 and stats2["orphans"] == 0,
          str(stats2))
    al = c.get("/api/admin/audit-logs?action=export_cleanup", headers=H(admin_t)).json()["data"]
    check("清理动作写入审计日志（2 次）", al["total"] == 2, str(al["total"]))
    d0 = al["list"][1]["detail"]
    check("审计详情结构化记录 ttlDays / 文件数",
          d0.get("ttlDays") == 7 and d0.get("deletedFiles") == 1 and d0.get("orphans") == 1,
          str(d0))
    check("审计对象为 dataset/exports",
          al["list"][0]["targetType"] == "dataset" and al["list"][0]["targetId"] == "exports",
          f"{al['list'][0]['targetType']}/{al['list'][0]['targetId']}")

    print("[导出清理] EXPORT_TTL_DAYS=0 关闭清理")
    check("settings 读取到 7", settings.export_ttl_days == 7, str(settings.export_ttl_days))
    off = asyncio.run(purge_with_ttl(0))
    check("ttl=0 → enabled False 且不删任何东西",
          off["enabled"] is False and off["deletedFiles"] == 0, str(off))
    check("关闭清理后未过期包仍在", exists("exports/job_new.zip"))

print(f"\n== 烟测结果：{len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    raise SystemExit(1)
