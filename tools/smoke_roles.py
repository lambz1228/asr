"""烟测：验证「普通用户=采集 / 管理员=导入·审核」两条通路的接口链路。

覆盖：管理员登录 → 导入任务（进公共池）→ 采集员登录 → 领取公共池 → 我的任务；
以及权限边界（采集员越权 403）与 PIPL 门禁（未签语音同意书上传 409）。

使用独立的临时 SQLite（_smoke_role.db），不污染开发库 asr.db。
运行：python tools/smoke_roles.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "asr-server")
os.chdir(SERVER)
sys.path.insert(0, SERVER)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_smoke_role.db"
os.environ["LOCAL_STORAGE_PATH"] = "./_smoke_data"
os.environ["ENV"] = "dev"
os.environ["DEV_MOCK_LOGIN"] = "true"
os.environ["SEED_DEMO"] = "true"          # 播种 u_demo(collector) / u_admin(admin)
os.environ["FFMPEG_ENABLED"] = "false"

# 每次从干净库开始：残留数据会让重复运行误判（例如「任务包已存在」）。
# 注意：WAL 模式下 SQLite 还会生成 -wal / -shm 侧车文件，必须一并删除，
# 否则残留的 WAL 会把上一次的写入带回来，表现为难以复现的假失败。
for _suf in ("", "-wal", "-shm", "-journal"):
    _p = os.path.join(SERVER, "_smoke_role.db" + _suf)
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
        payload = {"code": "smoke_" + (role or "default")}
        if role:
            payload["role"] = role
        b = c.post("/api/auth/wx-login", json=payload).json()
        assert b.get("code") == 0, b
        return b["data"]["token"]

    def H(t):
        return {"Authorization": "Bearer " + t}

    print("[管理员通路] 登录 → 导入任务")
    admin_t = login("admin")
    me = c.get("/api/auth/me", headers=H(admin_t)).json()
    check("管理员登录后角色=admin", me["data"]["role"] == "admin", str(me["data"]))

    imp = c.post(
        "/api/admin/packages/import",
        json={
            "pkgId": "pkg_smoke_roles",
            "name": "冒烟-角色分工",
            "params": {"sample_rate": 16000, "channels": 1, "format": "aac"},
            "texts": [{"text": "冒烟文本一"}, {"text": "冒烟文本二"}],
        },
        headers=H(admin_t),
    ).json()
    check("管理员导入任务成功", imp.get("code") == 0, str(imp.get("message")))
    check("导入生成 2 条任务", imp["data"]["createdAssignments"] == 2, str(imp.get("data")))
    check("assignee 留空进入公共池（公共池接口可见 2 条）",
          len(c.get("/api/tasks/pool", headers=H(admin_t)).json()["data"]["list"]) == 2)

    pkgs = c.get("/api/admin/packages", headers=H(admin_t)).json()
    check("管理员可查看任务包列表", any(p["pkgId"] == "pkg_smoke_roles" for p in pkgs["data"]["list"]))
    check("管理员可访问录音审核列表", c.get("/api/admin/audios", headers=H(admin_t)).status_code == 200)

    print("[普通用户通路] 登录 → 领取公共池 → 我的任务")
    col_t = login("collector")
    me2 = c.get("/api/auth/me", headers=H(col_t)).json()
    check("普通用户登录后角色=collector", me2["data"]["role"] == "collector", str(me2["data"]))

    mine0 = c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]
    check("采集员初始仅见分配给自己的 3 条演示任务", len(mine0) == 3, f"实际 {len(mine0)}")

    pool = c.get("/api/tasks/pool", headers=H(col_t)).json()["data"]["list"]
    tid = pool[0]["id"]
    cl = c.post(f"/api/tasks/{tid}/claim", headers=H(col_t)).json()
    check("领取公共池任务成功", cl["data"]["claimed"] is True, str(cl))

    check("领取后公共池剩 1 条",
          len(c.get("/api/tasks/pool", headers=H(col_t)).json()["data"]["list"]) == 1)
    mine1 = c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"]
    check("领取后任务出现在「我的任务」（3→4）", len(mine1) == 4, f"实际 {len(mine1)}")

    print("[权限边界] 采集员不可越权")
    r = c.post("/api/admin/packages/import", json={"texts": [{"text": "x"}]}, headers=H(col_t))
    check("采集员调用导入接口被拒 403", r.status_code == 403, str(r.status_code))
    check("采集员访问任务包列表被拒 403",
          c.get("/api/admin/packages", headers=H(col_t)).status_code == 403)
    check("采集员访问录音审核列表被拒 403",
          c.get("/api/admin/audios", headers=H(col_t)).status_code == 403)

    print("[PIPL 门禁] 未签语音同意书不可上传（409）")
    files = {"file": ("t.aac", b"\x00\x01", "audio/aac")}
    r = c.post(
        "/api/tasks/a1/upload",
        files=files,
        data={"textId": "t1", "uploadId": "smoke_up_1"},
        headers=H(col_t),
    )
    check("未签同意书上传被拒 409", r.status_code == 409, str(r.status_code))

print(f"\n== 烟测结果：{len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    raise SystemExit(1)
