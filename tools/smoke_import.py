"""烟测：Excel（序号/汉语文本）导入 + 统一下发。

覆盖：
  1) .xlsx 两列表（序号/汉语文本）解析正确，「序号」列被忽略
  2) distribute=all    → 每个采集员各拿到全部文本
  3) distribute=split  → 文本轮流分摊
  4) 不传 assignees    → 进公共池
  5) CSV 两列表 & 无表头 CSV 兜底解析
  6) 采集员侧 /tasks 立即可见（无需领取）

使用独立临时 SQLite（_smoke_import.db），不污染开发库。
运行：python tools/smoke_import.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "asr-server")
os.chdir(SERVER)
sys.path.insert(0, SERVER)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_smoke_import.db"
os.environ["LOCAL_STORAGE_PATH"] = "./_smoke_data"
os.environ["ENV"] = "dev"
os.environ["DEV_MOCK_LOGIN"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["FFMPEG_ENABLED"] = "false"

from openpyxl import Workbook  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

PASS, FAIL = [], []

TEXTS = [
    "今天有空吗？我们一起去街上逛逛，买点好吃的回来。",
    "手机没电了，我先充一会儿电，等下再和你聊天。",
    "晚上想看个电视吗？我们找好看的节目慢慢看。",
]


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("  | " + extra if extra else ""))


def make_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["序号", "汉语文本"])
    for i, t in enumerate(rows, 1):
        ws.append([i, t])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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

    def import_file(token, filename, blob, mime, **fields):
        return c.post(
            "/api/admin/packages/import",
            files={"file": (filename, blob, mime)},
            data=fields,
            headers=H(token),
        ).json()

    admin_t = login("admin")
    col_t = login("collector")

    print("[0] 采集员列表接口")
    users = c.get("/api/admin/users", headers=H(admin_t)).json()["data"]["list"]
    collectors = [u["userId"] for u in users if u["role"] == "collector"]
    check("只列出采集员账号", collectors == ["u_demo"], str(collectors))
    check("采集员无权查看用户列表", c.get("/api/admin/users", headers=H(col_t)).status_code == 403)

    print("[1] xlsx 两列表（序号 / 汉语文本）")
    res = import_file(admin_t, "录音文本.xlsx", make_xlsx(TEXTS), XLSX_MIME,
                      pkgId="pkg_xlsx_all", name="xlsx全量下发",
                      assignees="u_demo", distribute="all")
    check("导入成功", res.get("code") == 0, str(res.get("message")))
    d = res.get("data") or {}
    check("解析出 3 条文本", d.get("createdTexts") == 3, str(d))
    check("下发给 1 人 → 3 条子任务", d.get("createdAssignments") == 3, str(d))
    check("返回下发对象", d.get("assignees") == ["u_demo"], str(d.get("assignees")))

    base = len(c.get("/api/tasks", headers=H(col_t)).json()["data"]["list"])
    check("采集员「我的任务」直接可见（seed 3 + 新 3 = 6）", base == 6, f"实际 {base}")

    print("[2] distribute=all 多接收人 → 每人一份")
    res = import_file(admin_t, "录音文本.xlsx", make_xlsx(TEXTS), XLSX_MIME,
                      pkgId="pkg_xlsx_multi", assignees="u_demo,u_other", distribute="all")
    d = res.get("data") or {}
    check("3 文本 × 2 人 = 6 条子任务", d.get("createdAssignments") == 6, str(d))

    print("[3] distribute=split → 轮流分摊")
    res = import_file(admin_t, "录音文本.xlsx", make_xlsx(TEXTS), XLSX_MIME,
                      pkgId="pkg_xlsx_split", assignees="u_demo,u_other", distribute="split")
    d = res.get("data") or {}
    check("3 文本分摊给 2 人 = 3 条子任务", d.get("createdAssignments") == 3, str(d))

    print("[4] 不传 assignees → 公共池")
    res = import_file(admin_t, "录音文本.xlsx", make_xlsx(TEXTS), XLSX_MIME,
                      pkgId="pkg_xlsx_pool")
    d = res.get("data") or {}
    check("3 条全部进公共池", d.get("createdAssignments") == 3, str(d))
    pool = c.get("/api/tasks/pool", headers=H(col_t)).json()["data"]["list"]
    check("公共池可见这 3 条", len(pool) == 3, f"实际 {len(pool)}")

    print("[5] CSV 两列 / 无表头 CSV")
    csv_blob = ("序号,汉语文本\n" + "\n".join(f"{i},{t}" for i, t in enumerate(TEXTS, 1)) + "\n").encode("utf-8-sig")
    res = import_file(admin_t, "录音文本.csv", csv_blob, "text/csv",
                      pkgId="pkg_csv", assignees="u_demo", distribute="all")
    d = res.get("data") or {}
    check("CSV「序号,汉语文本」解析 3 条", d.get("createdTexts") == 3, str(d))

    raw_blob = ("\n".join(f"{i},{t}" for i, t in enumerate(TEXTS, 1)) + "\n").encode("utf-8")
    res = import_file(admin_t, "无表头.csv", raw_blob, "text/csv",
                      pkgId="pkg_csv_noheader", assignees="u_demo", distribute="all")
    d = res.get("data") or {}
    check("无表头 CSV 兜底解析 3 条", d.get("createdTexts") == 3, str(d))

    print("[6] 异常与边界")
    res = import_file(admin_t, "录音文本.xlsx", make_xlsx(TEXTS), XLSX_MIME, pkgId="pkg_xlsx_all")
    check("pkgId 重复被拒", res.get("code") == 1, str(res.get("message")))
    res = import_file(admin_t, "old.xls", b"\xd0\xcf\x11\xe0abc", "application/vnd.ms-excel", pkgId="pkg_xls")
    check("旧版 .xls 给出明确错误", res.get("code") == 1 and "xls" in (res.get("message") or "").lower(),
          str(res.get("message")))
    res = import_file(admin_t, "录音文本.xlsx", make_xlsx(TEXTS), XLSX_MIME, pkgId="pkg_bad_dist", distribute="abc")
    check("非法 distribute 被拒", res.get("code") == 1, str(res.get("message")))

    pkgs = c.get("/api/admin/packages", headers=H(admin_t)).json()["data"]["list"]
    p = next((x for x in pkgs if x["pkgId"] == "pkg_xlsx_all"), None)
    check("任务包列表含下发对象与公共池计数",
          bool(p) and p["assignees"] == ["u_demo"] and p["pool"] == 0, str(p))

print(f"\n== 烟测结果：{len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    raise SystemExit(1)
