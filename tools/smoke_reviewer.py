"""烟测：审核员(reviewer)角色权限 + 录音版本递增 + 退回原因回显。

覆盖本轮修复的三个缺陷：
1. reviewer 角色此前调任何 /admin 接口都 403（require_reviewer 定义了却没用）
2. Recording.version 硬编码为 1，重录不递增（方案 §10.2 要求版本递增、历史保留）
3. 审核员填写的退回原因在采集端看不到（退回后无从针对性重录）

使用独立临时 SQLite（_smoke_reviewer.db），不污染开发库 asr.db。
运行：python tools/smoke_reviewer.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "asr-server")
os.chdir(SERVER)
sys.path.insert(0, SERVER)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_smoke_reviewer.db"
os.environ["LOCAL_STORAGE_PATH"] = "./_smoke_data"
os.environ["ENV"] = "dev"
os.environ["DEV_MOCK_LOGIN"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["FFMPEG_ENABLED"] = "false"

# 每次从干净库开始，避免重复运行导致任务累积。
# 注意：WAL 模式下 SQLite 还会生成 -wal / -shm 侧车文件，必须一并删除，
# 否则残留的 WAL 会把上一次的写入带回来，表现为难以复现的假失败。
for _suf in ("", "-wal", "-shm", "-journal"):
    _p = os.path.join(SERVER, "_smoke_reviewer.db" + _suf)
    if os.path.exists(_p):
        os.remove(_p)

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("  | " + extra if extra else ""))


with TestClient(app) as c:
    def login(role=None):
        payload = {"code": "smoke_rev_" + (role or "default")}
        if role:
            payload["role"] = role
        b = c.post("/api/auth/wx-login", json=payload).json()
        assert b.get("code") == 0, b
        return b["data"]["token"]

    def H(t):
        return {"Authorization": "Bearer " + t}

    def set_role(admin_t, uid, role):
        return c.post(
            f"/api/admin/users/{uid}/role", json={"role": role}, headers=H(admin_t)
        )

    admin_t = login("admin")

    # ---------- 1. 审核员角色应当可用 ----------
    print("[审核员角色] 升 u_demo 为 reviewer → 审核台应可用")
    r = set_role(admin_t, "u_demo", "reviewer")
    check("管理员可将用户提升为 reviewer", r.json().get("code") == 0, str(r.json()))

    rev_t = login()  # 无 role 参数 → u_demo
    me = c.get("/api/auth/me", headers=H(rev_t)).json()
    check("reviewer 登录后 /auth/me 角色=reviewer", me["data"]["role"] == "reviewer", str(me["data"]))

    ra = c.get("/api/admin/audios", headers=H(rev_t))
    check("【修复】reviewer 可访问录音审核列表（原为 403）", ra.status_code == 200, str(ra.status_code))

    re_ = c.post("/api/admin/export", headers=H(rev_t))
    check("【修复】reviewer 可导出数据集（原为 403）", re_.status_code == 200, str(re_.status_code))

    check("reviewer 不可导入任务（403，导入仅 admin）",
          c.post("/api/admin/packages/import", json={"texts": [{"text": "x"}]},
                 headers=H(rev_t)).status_code == 403)
    check("reviewer 不可查看用户列表（403）",
          c.get("/api/admin/users", headers=H(rev_t)).status_code == 403)
    check("reviewer 不可改他人角色（403）",
          set_role(rev_t, "u_admin", "collector").status_code == 403)

    # ---------- 2. 权限边界仍然守得住 ----------
    print("[权限边界] 采集员仍不可访问管理接口")
    set_role(admin_t, "u_demo", "collector")
    col_t = login()
    me2 = c.get("/api/auth/me", headers=H(col_t)).json()
    check("采集员角色=collector", me2["data"]["role"] == "collector", str(me2["data"]))
    check("采集员访问审核列表仍被拒 403",
          c.get("/api/admin/audios", headers=H(col_t)).status_code == 403)

    # ---------- 3. 录音版本递增 + 退回原因回显 ----------
    print("[版本与退回] 同一任务上传两次 → 版本递增；退回后采集端可见原因")
    c.post("/api/auth/consent", json={"type": "voice_sensitive"}, headers=H(col_t))

    files = {"file": ("t.aac", b"\x00\x01\x02", "audio/aac")}
    up1 = c.post("/api/tasks/a1/upload", files=files,
                 data={"textId": "t1", "uploadId": "smoke_rev_up1"}, headers=H(col_t))
    check("第 1 次上传成功", up1.status_code == 200 and up1.json()["code"] == 0, str(up1.status_code))

    files2 = {"file": ("t.aac", b"\x00\x01\x02\x03", "audio/aac")}
    up2 = c.post("/api/tasks/a1/upload", files=files2,
                 data={"textId": "t1", "uploadId": "smoke_rev_up2"}, headers=H(col_t))
    check("第 2 次上传（重录）成功", up2.status_code == 200 and up2.json()["code"] == 0, str(up2.status_code))

    audios = c.get("/api/admin/audios", headers=H(admin_t)).json()["data"]["list"]
    mine = [a for a in audios if a["assignmentId"] == "a1"]
    versions = sorted(a["version"] for a in mine)
    check("【修复】同一任务两次上传生成 2 个录音版本", len(mine) == 2, f"实际 {len(mine)}")
    check("【修复】录音版本递增为 1、2（原恒为 1）", versions == [1, 2], str(versions))

    latest = next(a for a in mine if a["version"] == 2)
    rj = c.post(f"/api/admin/audios/{latest['recordingId']}/review",
                json={"action": "reject", "reason": "第二个字读错了"}, headers=H(admin_t))
    check("管理员退回录音成功", rj.json().get("code") == 0, str(rj.json()))

    tasks = c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]
    a1 = next((t for t in tasks if t["id"] == "a1"), None)
    check("任务状态变为 rejected", a1 and a1["status"] == "rejected", str(a1))
    check("【修复】采集端可见退回原因（原为空）",
          a1 and a1.get("rejectReason") == "第二个字读错了", str(a1.get("rejectReason") if a1 else None))

    # 未退回的任务不应带原因
    a2 = next((t for t in tasks if t["id"] == "a2"), None)
    check("未退回任务不带退回原因", a2 and a2.get("rejectReason") is None, str(a2))

print(f"\n== 烟测结果：{len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    raise SystemExit(1)
