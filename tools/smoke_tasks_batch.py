"""烟测：/tasks 退回原因「批量取最新一条」的正确性（N+1 修复后的回归保护）。

背景：list_tasks 原来是「每条 rejected 任务单独查一次 ReviewLog」的 N+1 写法，
退回件一多就是几十上百次数据库往返。改成一次批量查询 + 按 ReviewLog.id 倒序取
每个任务首次出现的记录。这个改写最容易错的点是「按顺序取首条」的语义，
所以单独用烟测把它钉住：

  1) 多条已退回任务 → 各自拿到**自己**的最新原因，不会串味
  2) 同一任务退回两次 → 只取**最新一次**的原因
  3) 未退回任务 → rejectReason 为 None
  4) 最新一次退回没填原因 → 返回空，**不能**回退到更早的那条原因
  5) 批量取数后 pkgName / textId 等字段仍然正确（join 没被破坏）

使用独立临时 SQLite（_smoke_tasks_batch.db），不污染开发库 asr.db。
运行：python tools/smoke_tasks_batch.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "asr-server")
os.chdir(SERVER)
sys.path.insert(0, SERVER)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_smoke_tasks_batch.db"
os.environ["LOCAL_STORAGE_PATH"] = "./_smoke_data"
os.environ["ENV"] = "dev"
os.environ["DEV_MOCK_LOGIN"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["FFMPEG_ENABLED"] = "false"

# 每次从干净库开始，避免重复运行导致任务累积
for _f in ("_smoke_tasks_batch.db",):
    _p = os.path.join(SERVER, _f)
    if os.path.exists(_p):
        os.remove(_p)

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

PASS, FAIL = [], []

TEXTS = [
    "第一条：今天天气很好，我们一起去公园散步。",
    "第二条：请把窗户关上，外面风有点大。",
    "第三条：这本书我看完了，可以借给你。",
    "第四条：明天早上八点在楼下集合。",
]


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("  | " + extra if extra else ""))


with TestClient(app) as c:

    def login(role=None):
        payload = {"code": "smoke_batch_" + (role or "default")}
        if role:
            payload["role"] = role
        b = c.post("/api/auth/wx-login", json=payload).json()
        assert b.get("code") == 0, b
        return b["data"]["token"]

    def H(t):
        return {"Authorization": "Bearer " + t}

    admin_t = login("admin")
    col_t = login()  # u_demo → collector

    # ---------- 准备：导入 4 条文本并全部下发给 u_demo ----------
    imp = c.post(
        "/api/admin/packages/import",
        json={"name": "批量退回烟测包", "texts": [{"text": t} for t in TEXTS], "assignees": ["u_demo"]},
        headers=H(admin_t),
    )
    check("导入任务包成功", imp.json().get("code") == 0, str(imp.json())[:160])
    pkg_id = imp.json()["data"]["pkgId"]

    c.post("/api/auth/consent", json={"type": "voice_sensitive"}, headers=H(col_t))
    all_tasks = c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]
    # SEED_DEMO 还会塞几条示例任务，这里只关心本次导入的任务包
    tasks = [t for t in all_tasks if t["pkgId"] == pkg_id]
    check("采集端可见本次下发的 4 条任务", len(tasks) == 4, f"实际 {len(tasks)}")
    check("任务文本与下发内容一致", [t["text"] for t in tasks] == TEXTS, str([t["text"] for t in tasks])[:80])
    check("pkgName 批量 join 正确", all(t["pkgName"] == "批量退回烟测包" for t in tasks),
          str({t["pkgName"] for t in tasks}))

    def upload(tid, text_id, tag):
        return c.post(
            f"/api/tasks/{tid}/upload",
            files={"file": ("t.aac", b"\x00\x01\x02\x03", "audio/aac")},
            data={"textId": text_id, "uploadId": tag},
            headers=H(col_t),
        )

    def latest_recording(tid, token):
        audios = c.get("/api/admin/audios", headers=H(token)).json()["data"]["list"]
        mine = [a for a in audios if a["assignmentId"] == tid]
        mine.sort(key=lambda a: a["version"])
        return mine[-1] if mine else None

    def reject(recording_id, reason, token):
        return c.post(
            f"/api/admin/audios/{recording_id}/review",
            json={"action": "reject", "reason": reason},
            headers=H(token),
        )

    # 四条任务全部上传
    for t in tasks:
        r = upload(t["id"], t["textId"], "batch_" + t["id"] + "_1")
        assert r.status_code == 200 and r.json().get("code") == 0, r.text

    # ---------- 1. 每条任务退回，理由各不相同 ----------
    print("[多任务互不串味] 4 条任务各退回一次，理由不同")
    reasons = {
        tasks[0]["id"]: "第三条读错字了",
        tasks[1]["id"]: "背景有狗叫声",
        tasks[2]["id"]: "",  # 留空：最新一次没填原因
        tasks[3]["id"]: "语速太快",
    }
    for tid, reason in reasons.items():
        rec = latest_recording(tid, admin_t)
        rr = reject(rec["recordingId"], reason, admin_t)
        assert rr.json().get("code") == 0, rr.text

    got = {t["id"]: t["rejectReason"] for t in c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]}
    for tid, reason in reasons.items():
        check(f"任务 {tid} 退回原因正确（批量取数不串味）",
              (got.get(tid) or "") == reason, f"期望 {reason!r} 实际 {got.get(tid)!r}")

    # ---------- 2. 同一任务退回两次 → 取最新一次 ----------
    print("[同任务多次退回] 取最新一次原因")
    tid = tasks[0]["id"]
    r2 = upload(tid, tasks[0]["textId"], "batch_" + tid + "_2")
    check("重录上传成功（版本递增）", r2.json().get("code") == 0, r2.text)
    rec2 = latest_recording(tid, admin_t)
    check("重录后新版本为 v2", rec2 and rec2["version"] == 2, str(rec2 and rec2["version"]))
    reject(rec2["recordingId"], "第二次：还有环境杂音", admin_t)
    got2 = {t["id"]: t["rejectReason"] for t in c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]}
    check("同一任务退回两次 → 只回显最新原因",
          got2.get(tid) == "第二次：还有环境杂音", f"实际 {got2.get(tid)!r}")
    check("同一任务的最新原因不会退回到更早的 v1 原因",
          got2.get(tid) != "第三条读错字了", f"实际 {got2.get(tid)!r}")

    # ---------- 3. 未退回任务不带原因 ----------
    print("[未退回任务] rejectReason 应为 None")
    approved_tid = tasks[3]["id"]
    rec3 = latest_recording(approved_tid, admin_t)
    ok = c.post(f"/api/admin/audios/{rec3['recordingId']}/review",
                json={"action": "approve"}, headers=H(admin_t))
    check("通过审核成功", ok.json().get("code") == 0, ok.text)
    got3 = {t["id"]: t["rejectReason"] for t in c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]}
    check("已通过任务不带退回原因", got3.get(approved_tid) is None, f"实际 {got3.get(approved_tid)!r}")

    # ---------- 4. 最新一次留空 → 不回退到更早的原因 ----------
    print("[留空原因] 最新一次没填 → 返回空，不能回退到旧原因")
    tid_empty = tasks[1]["id"]
    r4 = upload(tid_empty, tasks[1]["textId"], "batch_" + tid_empty + "_2")
    assert r4.json().get("code") == 0, r4.text
    rec4 = latest_recording(tid_empty, admin_t)
    reject(rec4["recordingId"], "", admin_t)
    got4 = {t["id"]: t["rejectReason"] for t in c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]}
    check("最新一次留空 → 不回退到上一次的「背景有狗叫声」",
          (got4.get(tid_empty) or "") == "", f"实际 {got4.get(tid_empty)!r}")

    # ---------- 5. N+1 回归护栏：SQL 语句数不随退回任务数线性增长 ----------
    print("[N+1 护栏] 60 条已退回任务 → 查一次 /tasks 只应发少量 SQL")
    N = 60
    big_texts = [{"text": f"批量护栏第 {i} 条文本内容。"} for i in range(N)]
    imp2 = c.post(
        "/api/admin/packages/import",
        json={"name": "N+1 护栏包", "texts": big_texts, "assignees": ["u_demo"]},
        headers=H(admin_t),
    )
    pkg2 = imp2.json()["data"]["pkgId"]
    big = [t for t in c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"] if t["pkgId"] == pkg2]
    check(f"批量下发 {N} 条任务", len(big) == N, f"实际 {len(big)}")

    for i, t in enumerate(big):
        r = upload(t["id"], t["textId"], f"bulk_{t['id']}")
        assert r.json().get("code") == 0, r.text
        rec = latest_recording(t["id"], admin_t)
        reject(rec["recordingId"], f"批量原因-{i}", admin_t)

    from sqlalchemy import event  # noqa: E402

    from app.db import engine  # noqa: E402

    stats = {"total": 0, "reviews": 0}

    def _before(conn, cursor, statement, params, context, executemany):
        stats["total"] += 1
        # 退回原因来自 reviews 表（模型类名 ReviewLog，表名 reviews）
        if "reviews.reason" in statement.lower():
            stats["reviews"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _before)
    t0 = time.perf_counter()
    res = c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]
    elapsed = (time.perf_counter() - t0) * 1000
    event.remove(engine.sync_engine, "before_cursor_execute", _before)

    mine_big = [t for t in res if t["pkgId"] == pkg2]
    check(f"{N} 条退回原因全部正确", all(
        (t["rejectReason"] or "") == f"批量原因-{i}" for i, t in enumerate(mine_big)
    ), str([t["rejectReason"] for t in mine_big[:3]]))
    check("查退回原因只有一条批量 SQL（N+1 已消除）",
          stats["reviews"] == 1, f"退回原因相关查询 {stats['reviews']} 次")
    check("整次 /tasks 的 SQL 次数为常数级",
          stats["total"] < 15, f"共 {stats['total']} 次 SQL")
    print(f"        → {N} 条任务时 /tasks 共 {stats['total']} 次 SQL（其中退回原因 {stats['reviews']} 次），"
          f"耗时 {elapsed:.1f} ms")
    print(f"        → 修复前的写法同样场景需要 {N}+ 次 ReviewLog 查询")

print(f"\n== 烟测结果：{len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    raise SystemExit(1)
