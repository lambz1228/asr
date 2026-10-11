"""烟测：进度统计 + 导出内容完整性 + 录音中断标记。

覆盖本轮补齐的三项：
1. 进度统计：GET /api/progress（采集员个人）、GET /api/admin/progress（全局）
2. 导出：ZIP 含 audio/ + metadata.csv（完整字段）+ transcripts.txt + manifest.json；
   并校验 §6.1 完整性（音频缺失时中止导出）
3. 录音中断：上传带 interrupted=1 → quality_flags 含 recording_interrupted

使用独立临时 SQLite（_smoke_prog.db），不污染开发库 asr.db。
运行：python tools/smoke_progress_export.py
"""
import csv
import io
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "asr-server")
os.chdir(SERVER)
sys.path.insert(0, SERVER)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_smoke_prog.db"
os.environ["LOCAL_STORAGE_PATH"] = "./_smoke_data"
os.environ["ENV"] = "dev"
os.environ["DEV_MOCK_LOGIN"] = "true"
os.environ["SEED_DEMO"] = "true"
os.environ["FFMPEG_ENABLED"] = "false"

# 每次从干净库 + 干净存储开始：残留记录/音频会让导出计数对不上。
# 注意：WAL 模式下 SQLite 还会生成 -wal / -shm 侧车文件，必须一并删除，
# 否则残留的 WAL 会把上一次的写入带回来，表现为难以复现的假失败。
for _suf in ("", "-wal", "-shm", "-journal"):
    _p = os.path.join(SERVER, "_smoke_prog.db" + _suf)
    if os.path.exists(_p):
        os.remove(_p)
import shutil as _shutil  # noqa: E402

_shutil.rmtree(os.path.join(SERVER, "_smoke_data"), ignore_errors=True)

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("  | " + extra if extra else ""))


with TestClient(app) as c:
    def login(role=None):
        payload = {"code": "smoke_prog_" + (role or "default")}
        if role:
            payload["role"] = role
        b = c.post("/api/auth/wx-login", json=payload).json()
        assert b.get("code") == 0, b
        return b["data"]["token"]

    def H(t):
        return {"Authorization": "Bearer " + t}

    admin_t = login("admin")
    col_t = login()

    print("[进度统计] 采集员个人进度")
    p0 = c.get("/api/progress", headers=H(col_t)).json()["data"]
    check("初始：播种 3 条任务全部待录", p0["total"] == 3 and p0["pending"] == 3, str(p0))
    check("初始：完成率 0", p0["completionRate"] == 0, str(p0["completionRate"]))
    check("个人进度含 recorded 字段", p0.get("recorded") == 0, str(p0))

    # 造数：导入一个任务包（验证 param_version）+ 上传一条带中断标记的录音
    imp = c.post(
        "/api/admin/packages/import",
        json={
            "pkgId": "pkg_smoke_prog",
            "name": "冒烟-进度导出",
            "params": {"sample_rate": 16000, "channels": 1, "format": "aac"},
            "texts": [{"text": "进度统计用文本"}],
            "assignees": ["u_demo"],
        },
        headers=H(admin_t),
    ).json()
    check("导入任务包成功（下发 u_demo）", imp.get("code") == 0, str(imp.get("message")))

    pkgs = c.get("/api/admin/packages", headers=H(admin_t)).json()["data"]["list"]
    mine_pkg = next((p for p in pkgs if p["pkgId"] == "pkg_smoke_prog"), None)
    check("任务包暴露 paramVersion 字段（方案 §10.2）",
          mine_pkg is not None and mine_pkg.get("paramVersion") == 1, str(mine_pkg))

    p1 = c.get("/api/progress", headers=H(col_t)).json()["data"]
    check("下发后任务数 3→4", p1["total"] == 4, str(p1))

    print("[录音中断] 上传带 interrupted=1 的录音")
    c.post("/api/auth/consent", json={"type": "voice_sensitive"}, headers=H(col_t))
    files = {"file": ("t.aac", b"\x00\x01\x02", "audio/aac")}
    up = c.post(
        "/api/tasks/a1/upload",
        files=files,
        data={"textId": "t1", "uploadId": "smoke_prog_up1", "interrupted": "1"},
        headers=H(col_t),
    ).json()
    check("上传成功", up.get("code") == 0, str(up.get("message")))
    check("中断标记写入 quality_flags（recording_interrupted）",
          "recording_interrupted" in up["data"]["qualityFlags"], str(up["data"]["qualityFlags"]))

    p2 = c.get("/api/progress", headers=H(col_t)).json()["data"]
    check("上传后：待录 3、待审 1", p2["pending"] == 3 and p2["uploaded"] == 1, str(p2))
    check("上传后：完成率仍为 0（未审核通过）", p2["completionRate"] == 0, str(p2["completionRate"]))

    print("[进度统计] 管理端全局进度")
    audios = c.get("/api/admin/audios", headers=H(admin_t)).json()["data"]["list"]
    rid = audios[0]["recordingId"]
    c.post(f"/api/admin/audios/{rid}/review", json={"action": "approve"}, headers=H(admin_t))

    g = c.get("/api/admin/progress", headers=H(admin_t)).json()["data"]
    check("全局：总任务 4、已通过 1", g["total"] == 4 and g["approved"] == 1, str(g))
    check("全局：完成率 0.25", g["completionRate"] == 0.25, str(g["completionRate"]))
    check("全局：含公共池计数字段", "pool" in g, str(list(g.keys())))
    check("全局：含按采集员统计（u_demo）",
          any(x["userId"] == "u_demo" and x["approved"] == 1 for x in g["collectors"]),
          str(g["collectors"]))
    check("全局：含按任务包统计（pkg_demo）",
          any(x["pkgId"] == "pkg_demo" for x in g["packages"]), str(g["packages"]))

    # reviewer 也能读全局进度；collector 不能
    c.post("/api/admin/users/u_demo/role", json={"role": "reviewer"}, headers=H(admin_t))
    rev_t = login()
    check("reviewer 可读全局进度",
          c.get("/api/admin/progress", headers=H(rev_t)).status_code == 200)
    c.post("/api/admin/users/u_demo/role", json={"role": "collector"}, headers=H(admin_t))
    col_t2 = login()
    check("采集员读全局进度被拒 403",
          c.get("/api/admin/progress", headers=H(col_t2)).status_code == 403)

    print("[导出] ZIP 内容完整性")
    r = c.post("/api/admin/export", headers=H(admin_t))
    check("导出返回 ZIP", r.status_code == 200 and r.headers["content-type"] == "application/zip",
          f"{r.status_code} {r.headers.get('content-type')}")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    check("ZIP 含 metadata.csv", "metadata.csv" in names, str(names))
    check("ZIP 含 transcripts.txt（方案 §6.3 新增）", "transcripts.txt" in names, str(names))
    check("ZIP 含 manifest.json", "manifest.json" in names, str(names))
    check("ZIP 含 audio/ 音频", any(n.startswith("audio/") for n in names), str(names))

    # metadata.csv 完整字段（§6.3）
    meta_raw = zf.read("metadata.csv").decode("utf-8")
    rows = list(csv.reader(io.StringIO(meta_raw)))
    header, body = rows[0], rows[1:]
    required = ["recordingId", "text", "collector", "recordedAt", "duration",
                "sampleRate", "channels", "paramVersion", "status"]
    missing = [col for col in required if col not in header]
    check("metadata.csv 含全部必需字段（含 text/collector/recordedAt/paramVersion）",
          not missing, f"缺 {missing}；实际 {header}")
    check("metadata.csv 行数=已通过数 1", len(body) == 1, f"实际 {len(body)}")
    row = dict(zip(header, body[0]))
    check("metadata 文本列有内容", bool(row.get("text")), str(row.get("text")))
    check("metadata 采集人列 = u_demo", row.get("collector") == "u_demo", str(row.get("collector")))
    check("metadata 采集时间非空", bool(row.get("recordedAt")), str(row.get("recordedAt")))
    check("metadata 参数版本 = 1", row.get("paramVersion") == "1", str(row.get("paramVersion")))

    # transcripts.txt
    tr = zf.read("transcripts.txt").decode("utf-8")
    lines = [x for x in tr.splitlines() if x.strip()]
    check("transcripts.txt 行数=音频数 1", len(lines) == 1, f"实际 {len(lines)}")
    check("transcripts.txt 每行含音频编号（编号与音频对应）",
          lines and lines[0].split("\t")[0] == rid, str(lines))

    # manifest.json
    man = json.loads(zf.read("manifest.json").decode("utf-8"))
    check("manifest 含 total 与导出时间", man.get("total") == 1 and bool(man.get("exportedAt")), str(man.get("total")))
    check("manifest 每条含 md5", bool(man["items"][0].get("md5")), str(man["items"][0]))

    print("[导出] §6.1 完整性校验：音频缺失时中止")
    shutil.rmtree("./_smoke_data", ignore_errors=True)
    r2 = c.post("/api/admin/export", headers=H(admin_t))
    body2 = r2.json()
    check("音频缺失时导出被中止并返回 code=1",
          body2.get("code") == 1 and "缺失" in (body2.get("message") or ""), str(body2.get("message")))

print(f"\n== 烟测结果：{len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    raise SystemExit(1)
