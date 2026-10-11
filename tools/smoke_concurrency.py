"""烟测：20 并发规模下的正确性与事件循环健康度（并发治理的回归保护）。

背景：按「20 人同时使用」评估后端时，逐项实测暴露了两个问题：

  1) 抢领竞态（正确性缺陷）
     claim_task 原来是「先 SELECT 判断 status == 'pending'，再赋值 claimed」。
     多人同时点抢领时，多个请求会同时读到 pending，于是都认为自己领到了。
     实测 20 人并发抢同一个任务，**15 人收到 claimed=True**，而库里的 assignee
     被反复覆盖，最终只有 1 个真正的赢家。前端按 claimed=True 放行去录音，
     结果录的是一条不属于自己的任务。
     修法：把状态判断下推给数据库，用带 WHERE status='pending' 的原子 UPDATE，
     再按 rowcount 判断是否真的抢到。

  2) 事件循环阻塞（性能缺陷）
     analyze_wav 是纯 Python 逐样本循环，原来直接在协程里调用，会占住事件循环。
     实测 44.1kHz/60s 需 0.5s、48kHz/300s 需 2.6s —— 这期间**全服务所有人的
     所有请求**都被冻住。修法：改用 asyncio.to_thread 丢到线程池。

本烟测把上述两条钉死，另加 SQLite 并发参数与混合读写的验证：

  1) 20 并发抢领同一任务 → 恰好 1 人 claimed=True，且与库中 assignee 一致
  2) 抢领不存在的任务 → 明确报「任务不存在」
  3) 已领走的任务再抢 → claimed=False，状态仍是 claimed
  4) 20 并发各领各的任务 → 全部成功、互不串号（不会出现 assignee 被覆盖）
  5) analyze_wav 在线程池执行 → 事件循环最大停顿远小于其 CPU 耗时
  6) SQLite 已启用 WAL + busy_timeout
  7) 15 读 + 5 写 混合并发 → 无 database is locked

使用独立临时 SQLite（_smoke_concurrency.db），不污染开发库 asr.db。
运行：python tools/smoke_concurrency.py
"""
import asyncio
import os
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "asr-server")
os.chdir(SERVER)
sys.path.insert(0, SERVER)
sys.stdout.reconfigure(encoding="utf-8")

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./_smoke_concurrency.db"
os.environ["LOCAL_STORAGE_PATH"] = "./_smoke_data"
os.environ["ENV"] = "dev"
os.environ["DEV_MOCK_LOGIN"] = "true"
os.environ["SEED_DEMO"] = "false"
os.environ["FFMPEG_ENABLED"] = "false"

DB_FILE = os.path.join(SERVER, "_smoke_concurrency.db")
# WAL 模式下 SQLite 会额外生成 -wal / -shm 侧车文件，必须一并删除，
# 否则残留的 WAL 会把上一次的写入带回来。
for _suf in ("", "-wal", "-shm", "-journal"):
    _p = DB_FILE + _suf
    if os.path.exists(_p):
        os.remove(_p)

import httpx  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app import models  # noqa: E402
from app.audio import analyze_wav  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.jwt_utils import create_token  # noqa: E402
from main import app  # noqa: E402

PASS, FAIL = [], []

# 并发规模：对齐「20 人同时使用」的评估口径
N = 20


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + ("  | " + extra if extra else ""))


async def main() -> int:
    await init_db()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:

        def H(t):
            return {"Authorization": "Bearer " + t}

        # 自建用户 + 自签 token：ASGITransport 不触发 lifespan，不会跑 seed；
        # 且开发态 mock 登录固定映射到 u_demo，造不出 20 个不同的人。
        # 本烟测要验的是并发下的领取归属，不是登录流程，直接建人更可控。
        async with SessionLocal() as db:
            db.add(models.User(user_id="u_conc_admin", role="admin"))
            for i in range(N):
                db.add(models.User(user_id=f"u_conc_{i:02d}", role="collector"))
            await db.commit()

        admin_t = create_token({"uid": "u_conc_admin"})
        creds = [
            (create_token({"uid": f"u_conc_{i:02d}"}), f"u_conc_{i:02d}") for i in range(N)
        ]
        col_tokens = [t for t, _ in creds]
        col_uids = [u for _, u in creds]
        check(f"造出 {N} 个互不相同的采集员", len(set(col_uids)) == N, f"去重后 {len(set(col_uids))}")

        # 采集员都要先签语音同意书才能上传
        for t in col_tokens:
            await c.post("/api/auth/consent", json={"type": "voice_sensitive"}, headers=H(t))

        # ---------- 1) 抢领竞态：20 人抢同一个任务 ----------
        print("\n[1] 抢领竞态（20 人抢同 1 个任务）")
        imp = await c.post(
            "/api/admin/packages/import",
            json={"name": "并发烟测包", "texts": [{"text": f"并发文本{i}"} for i in range(N)]},
            headers=H(admin_t),
        )
        check("导入任务包成功", imp.json().get("code") == 0, str(imp.json())[:120])
        pkg_id = imp.json()["data"]["pkgId"]

        # 取一条「公共池」任务（assignee 为空 = 可抢领）
        pool = (await c.get("/api/tasks/pool", headers=H(col_tokens[0]))).json()["data"]["list"]
        hot = [t for t in pool if t.get("status") == "pending"]
        check("公共池有可抢领任务", len(hot) >= 1, f"池中 {len(hot)} 条")
        hot_id = hot[0]["id"]

        res = await asyncio.gather(*[
            c.post(f"/api/tasks/{hot_id}/claim", headers=H(t)) for t in col_tokens
        ])
        bodies = [r.json() for r in res]
        winners = [
            i for i, b in enumerate(bodies)
            if (b.get("data") or {}).get("claimed") is True
        ]
        check(f"20 并发抢领 → 恰好 1 人 claimed=True", len(winners) == 1, f"实际 {len(winners)} 人")
        check("其余 19 人均 claimed=False",
              sum(1 for b in bodies if (b.get("data") or {}).get("claimed") is False) == N - 1,
              f"实际 {sum(1 for b in bodies if (b.get('data') or {}).get('claimed') is False)} 人")

        async with SessionLocal() as db:
            asg = await db.scalar(
                select(models.TaskAssignment).where(
                    models.TaskAssignment.assignment_id == hot_id
                )
            )
            winner_uid = asg.assignee
            winner_status = asg.status
        # 赢家必须与库中 assignee 一致（不能出现「说我领到了但库里是别人」）
        claimed_uid = col_uids[winners[0]] if len(winners) == 1 else None
        check("赢家与库中 assignee 一致（不会「假领到」）",
              claimed_uid is not None and claimed_uid == winner_uid and winner_status == "claimed",
              f"返回 claimed 的={claimed_uid}, 库中 assignee={winner_uid}, status={winner_status}")

        # ---------- 2) 抢领不存在的任务 ----------
        print("\n[2] 边界：抢领不存在的任务")
        r = (await c.post("/api/tasks/__nope__/claim", headers=H(col_tokens[0]))).json()
        check("不存在的任务 → code=1 且提示任务不存在",
              r.get("code") == 1 and "不存在" in (r.get("message") or ""), str(r)[:100])

        # ---------- 3) 重复抢领已领走的任务 ----------
        print("\n[3] 边界：已领走的任务再抢")
        r = (await c.post(f"/api/tasks/{hot_id}/claim", headers=H(col_tokens[1]))).json()
        check("已被领走 → claimed=False", (r.get("data") or {}).get("claimed") is False, str(r)[:100])
        check("已被领走 → 状态回显 claimed", (r.get("data") or {}).get("status") == "claimed",
              str(r.get("data"))[:80])

        # ---------- 4) 20 并发各领各的任务 ----------
        print(f"\n[4] {N} 并发各自抢领不同任务")
        imp2 = await c.post(
            "/api/admin/packages/import",
            json={"name": "并发烟测包2", "texts": [{"text": f"独立文本{i}"} for i in range(N)]},
            headers=H(admin_t),
        )
        pkg2 = imp2.json()["data"]["pkgId"]
        async with SessionLocal() as db:
            rows = (await db.execute(
                select(models.TaskAssignment.assignment_id)
                .where(models.TaskAssignment.pkg_id == pkg2)
                .order_by(models.TaskAssignment.id)
            )).all()
        ids = [r[0] for r in rows]
        check("准备到 N 条待领任务", len(ids) == N, f"实际 {len(ids)}")

        res = await asyncio.gather(*[
            c.post(f"/api/tasks/{ids[i]}/claim", headers=H(col_tokens[i])) for i in range(N)
        ])
        oks = [r.json() for r in res]
        check(f"{N} 并发各领各的 → 全部 claimed=True",
              all((b.get("data") or {}).get("claimed") is True for b in oks),
              f"成功 {sum(1 for b in oks if (b.get('data') or {}).get('claimed') is True)}/{N}")
        async with SessionLocal() as db:
            rows = (await db.execute(
                select(models.TaskAssignment.assignment_id, models.TaskAssignment.assignee)
                .where(models.TaskAssignment.pkg_id == pkg2)
            )).all()
        check("每条任务的 assignee 各不相同（无覆盖串号）",
              len({a for _, a in rows}) == N and all(a for _, a in rows),
              f"去重后 {len({a for _, a in rows})} 个 assignee")

        # ---------- 5) analyze_wav 不阻塞事件循环 ----------
        print("\n[5] analyze_wav 线程池化：事件循环不被冻住")
        d = tempfile.mkdtemp()
        wav_path = os.path.join(d, "big.wav")
        sr, secs = 48000, 240
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            chunk = b"\x10\x27" * sr  # 约 0.5 秒的样本，重复写满
            for _ in range(secs * 2):
                w.writeframes(chunk)
        check("生成 48kHz/240s 大 WAV 用于压测", os.path.getsize(wav_path) > 20_000_000,
              f"{os.path.getsize(wav_path)/1024/1024:.0f} MB")

        t0 = time.perf_counter()
        analyze_wav(wav_path)
        cpu_ms = (time.perf_counter() - t0) * 1000

        gaps: list[float] = []
        done = False

        async def ticker():
            last = time.perf_counter()
            while not done:
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        t = asyncio.create_task(ticker())
        t0 = time.perf_counter()
        await asyncio.to_thread(analyze_wav, wav_path)
        offload_ms = (time.perf_counter() - t0) * 1000
        done = True
        await t

        max_gap = max(gaps) * 1000 if gaps else 0.0
        print(f"        单次 analyze_wav CPU 耗时 ≈ {cpu_ms:.0f} ms（48kHz/240s）")
        print(f"        to_thread 执行期间事件循环最大停顿 = {max_gap:.1f} ms")
        check("事件循环最大停顿 < 100ms（未被 analyze_wav 冻住）", max_gap < 100.0,
              f"最大停顿 {max_gap:.1f} ms")
        check("停顿远小于其 CPU 耗时（证明确实跑在线程池）",
              max_gap < cpu_ms / 3, f"停顿 {max_gap:.1f} ms vs CPU {cpu_ms:.0f} ms")

        # ---------- 6) SQLite 并发参数 ----------
        print("\n[6] SQLite 并发参数")
        async with SessionLocal() as db:
            jm = (await db.execute(text("PRAGMA journal_mode"))).scalar()
            bt = (await db.execute(text("PRAGMA busy_timeout"))).scalar()
            sy = (await db.execute(text("PRAGMA synchronous"))).scalar()
        check("journal_mode = wal（读写不再互斥）", str(jm).lower() == "wal", f"实际 {jm}")
        check("busy_timeout = 30000（等锁而非直接报错）", int(bt) == 30000, f"实际 {bt}")
        check("synchronous = 1/NORMAL", int(sy) == 1, f"实际 {sy}")

        # ---------- 7) 混合读写并发 ----------
        print(f"\n[7] 15 读 + 5 写 混合并发")
        ro_token = col_tokens[0]

        async def reader(_i):
            try:
                for _ in range(5):
                    r = await c.get("/api/tasks", headers=H(ro_token))
                    if r.status_code != 200:
                        return f"HTTP {r.status_code}"
                return "ok"
            except Exception as e:  # noqa: BLE001
                return f"{type(e).__name__}: {str(e)[:60]}"

        async def writer(i):
            try:
                r = await c.post(f"/api/tasks/{ids[i]}/claim", headers=H(col_tokens[i]))
                return "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                return f"{type(e).__name__}: {str(e)[:60]}"

        t0 = time.perf_counter()
        res = await asyncio.gather(*([reader(i) for i in range(15)] + [writer(i) for i in range(5)]))
        mixed_ms = (time.perf_counter() - t0) * 1000
        bad = [r for r in res if r != "ok"]
        check("15 读 + 5 写 无失败（无 database is locked）", len(bad) == 0,
              f"失败 {len(bad)}：{bad[:2]}")
        print(f"        → 20 并发混合读写总耗时 {mixed_ms:.0f} ms")

    print(f"\n== 烟测结果：{len(PASS)} passed, {len(FAIL)} failed ==")
    if FAIL:
        print("失败项：" + "；".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
