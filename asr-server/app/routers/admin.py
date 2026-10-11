import asyncio
import csv
import hashlib
import io
import json
import uuid
import zipfile
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from .. import models
from ..cleanup import purge_expired_exports
from ..config import settings
from ..db import SessionLocal
from ..deps import get_db, record_audit, require_admin, require_reviewer
from ..responses import fail, ok
from ..schemas import ReviewPayload
from ..stats import summarize
from ..storage import storage

router = APIRouter()

# 超过该阈值时导出改为异步任务（避免长请求阻塞 + 便于大批量流式打包）
EXPORT_ASYNC_THRESHOLD = 1000

# 允许分配的角色
ALLOWED_ROLES = {"collector", "reviewer", "admin"}


@router.get("/admin/progress")
async def global_progress(principal=Depends(require_reviewer), db=Depends(get_db)):
    """全局采集进度（方案 §9.1）：总量 / 各状态 / 完成率 + 公共池 + 按采集员排行 + 按任务包统计。

    完成率 = 已通过 / 总任务数（审核通过才计入完成）。
    """
    # 总览
    rows = await db.execute(
        select(models.TaskAssignment.status, func.count()).group_by(
            models.TaskAssignment.status
        )
    )
    overall = summarize({st: n for st, n in rows.all()})

    # 公共池：未指派且未被领取
    pool = await db.scalar(
        select(func.count())
        .select_from(models.TaskAssignment)
        .where(
            models.TaskAssignment.assignee.is_(None),
            models.TaskAssignment.status == "pending",
        )
    )

    # 按采集员
    crows = await db.execute(
        select(
            models.TaskAssignment.assignee,
            models.TaskAssignment.status,
            func.count(),
        )
        .where(models.TaskAssignment.assignee.is_not(None))
        .group_by(models.TaskAssignment.assignee, models.TaskAssignment.status)
    )
    per_user: dict[str, dict] = {}
    for uid, st, n in crows.all():
        per_user.setdefault(uid, {})[st] = n
    collectors = [{"userId": uid, **summarize(c)} for uid, c in per_user.items()]
    # 完成率高的排前面；同率则任务量大的排前面
    collectors.sort(key=lambda x: (-x["completionRate"], -x["total"]))

    # 按任务包
    prows = await db.execute(
        select(models.TaskAssignment.pkg_id, models.TaskAssignment.status, func.count())
        .group_by(models.TaskAssignment.pkg_id, models.TaskAssignment.status)
    )
    per_pkg: dict[str, dict] = {}
    for pid, st, n in prows.all():
        per_pkg.setdefault(pid, {})[st] = n
    names = dict(
        (await db.execute(select(models.TaskPackage.pkg_id, models.TaskPackage.name))).all()
    )
    packages = [
        {"pkgId": pid, "name": names.get(pid, pid), **summarize(c)}
        for pid, c in per_pkg.items()
    ]
    packages.sort(key=lambda x: x["pkgId"])

    return ok({**overall, "pool": pool, "collectors": collectors, "packages": packages})


@router.get("/admin/audit-logs")
async def list_audit_logs(
    action: str = "",
    operator: str = "",
    target_type: str = Query("", alias="targetType"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal=Depends(require_admin),
    db=Depends(get_db),
):
    """审计日志查询（方案 §9.1）：谁在什么时候对什么做了什么。

    此前 AuditLog 只写不查，管理员看不到操作记录。现支持按操作类型 / 操作人 /
    对象类型过滤 + 分页。含角色调整等敏感记录，故限管理员。
    """
    conds = []
    if action:
        conds.append(models.AuditLog.action == action)
    if operator:
        conds.append(models.AuditLog.operator_id == operator)
    if target_type:
        conds.append(models.AuditLog.target_type == target_type)

    total = await db.scalar(select(func.count()).select_from(models.AuditLog).where(*conds))
    rows = await db.execute(
        select(models.AuditLog)
        .where(*conds)
        .order_by(models.AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        {
            "id": a.id,
            "operatorId": a.operator_id,
            "operatorRole": a.operator_role,
            "action": a.action,
            "targetType": a.target_type,
            "targetId": a.target_id,
            "detail": a.detail or {},
            "ip": a.ip or "",
            "createdAt": a.created_at.isoformat() if a.created_at else "",
        }
        for a in rows.scalars()
    ]
    # 供前端渲染筛选项：全表出现过的操作类型（不受当前过滤影响）
    actions = [
        x
        for (x,) in (
            await db.execute(
                select(models.AuditLog.action).distinct().order_by(models.AuditLog.action)
            )
        ).all()
    ]
    return ok(
        {
            "list": items,
            "total": total or 0,
            "limit": limit,
            "offset": offset,
            "actions": actions,
        }
    )


@router.get("/admin/audios")
async def list_audios(principal=Depends(require_reviewer), db=Depends(get_db)):
    rows = await db.execute(
        select(models.Recording).order_by(models.Recording.created_at.desc()).limit(200)
    )
    items = []
    for r in rows.scalars():
        preview_key = r.wav_key or r.raw_key
        url = await storage.url(preview_key) if preview_key else ""
        items.append(
            {
                "recordingId": r.recording_id,
                "assignmentId": r.assignment_id,
                "version": r.version,
                "status": r.status,
                "realSampleRate": r.real_sample_rate,
                "realChannels": r.real_channels,
                "realCodec": r.real_codec,
                "duration": r.duration,
                "qualityFlags": r.quality_flags,
                "transcode": r.transcode_status,
                "previewUrl": url,
            }
        )
    return ok({"list": items})


@router.post("/admin/audios/{recording_id}/review")
async def review_audio(
    recording_id: str,
    payload: ReviewPayload,
    principal=Depends(require_reviewer),
    db=Depends(get_db),
):
    if payload.action not in ("approve", "reject"):
        return {"code": 1, "message": "action 必须为 approve 或 reject", "data": None}

    rec = await db.scalar(
        select(models.Recording).where(models.Recording.recording_id == recording_id)
    )
    if not rec:
        raise HTTPException(404, "录音不存在")

    rec.status = "approved" if payload.action == "approve" else "rejected"
    db.add(
        models.ReviewLog(
            recording_id=recording_id,
            reviewer=principal["uid"],
            action=payload.action,
            reason=payload.reason,
        )
    )
    asg = await db.scalar(
        select(models.TaskAssignment).where(
            models.TaskAssignment.assignment_id == rec.assignment_id
        )
    )
    if asg:
        asg.status = rec.status

    record_audit(
        db,
        principal["uid"],
        principal["role"],
        "review",
        "recording",
        recording_id,
        {"action": payload.action, "reason": payload.reason},
    )
    await db.commit()
    return ok({"status": rec.status})


# metadata.csv 列定义（方案 §6.3：音频编号、文本、人员、时间、时长、采样率、声道、参数版本、审核状态）
EXPORT_METADATA_COLUMNS = [
    "recordingId",
    "assignmentId",
    "packageId",
    "paramVersion",
    "textId",
    "text",
    "collector",
    "recordedAt",
    "version",
    "duration",
    "sampleRate",
    "channels",
    "codec",
    "qualityFlags",
    "status",
]


async def _collect_export_rows(db) -> list[dict]:
    """汇总「已通过」录音的完整导出信息：音频键 + 文本 + 采集人 + 参数版本。"""
    rows = await db.execute(
        select(
            models.Recording,
            models.TaskAssignment,
            models.TextItem,
            models.TaskPackage,
        )
        .join(
            models.TaskAssignment,
            models.TaskAssignment.assignment_id == models.Recording.assignment_id,
        )
        .outerjoin(
            models.TextItem, models.TextItem.text_id == models.TaskAssignment.text_id
        )
        .outerjoin(
            models.TaskPackage, models.TaskPackage.pkg_id == models.TaskAssignment.pkg_id
        )
        .where(models.Recording.status == "approved")
        .order_by(models.Recording.id)
    )
    out: list[dict] = []
    for rec, asg, text, pkg in rows.all():
        key = rec.wav_key or rec.raw_key
        ext = "wav" if rec.wav_key else (key.rsplit(".", 1)[-1] if key else "bin")
        out.append(
            {
                "recordingId": rec.recording_id,
                "assignmentId": rec.assignment_id,
                "packageId": asg.pkg_id if asg else "",
                "paramVersion": pkg.param_version if pkg else None,
                "textId": asg.text_id if asg else "",
                "text": text.text if text else "",
                "collector": (asg.assignee if asg else "") or "",
                "recordedAt": rec.created_at.isoformat() if rec.created_at else "",
                "version": rec.version,
                "duration": rec.duration,
                "sampleRate": rec.real_sample_rate,
                "channels": rec.real_channels,
                "codec": rec.real_codec,
                "qualityFlags": list(rec.quality_flags or []),
                "status": rec.status,
                "key": key,
                "file": f"audio/{rec.recording_id}.{ext}",
            }
        )
    return out


async def _build_export_zip(rows: list[dict]) -> io.BytesIO:
    """构造 数据集.zip = audio/ + metadata.csv + transcripts.txt + manifest.json（方案 §6.3）。

    完整性校验（§6.1）：任一已通过录音的音频文件读取失败即中止导出，
    避免交付「台账有记录、ZIP 里没文件」的不完整数据集。
    """
    # 1) 先取音频；读不到 = 文件缺失，属 §6.1 的不一致，直接中止
    payload: list[tuple[dict, bytes]] = []
    missing: list[str] = []
    for row in rows:
        data = b""
        if row["key"]:
            try:
                data = await storage.read(row["key"])
            except Exception:
                data = b""
        if not data:
            missing.append(row["recordingId"])
        payload.append((row, data))
    if missing:
        raise ValueError(
            f"导出中止：{len(missing)} 条已通过录音的音频文件缺失"
            f"（如 {missing[:3]}），请检查对象存储后重试"
        )

    buf = io.BytesIO()
    manifest = {
        "total": len(rows),
        "exportedAt": models.utcnow().isoformat(),
        "items": [],
    }
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(EXPORT_METADATA_COLUMNS)
    transcript_lines: list[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for row, data in payload:
            z.writestr(row["file"], data)
            writer.writerow(
                [
                    row["recordingId"],
                    row["assignmentId"],
                    row["packageId"],
                    row["paramVersion"],
                    row["textId"],
                    row["text"],
                    row["collector"],
                    row["recordedAt"],
                    row["version"],
                    row["duration"],
                    row["sampleRate"],
                    row["channels"],
                    row["codec"],
                    ",".join(row["qualityFlags"]),
                    row["status"],
                ]
            )
            # transcripts.txt：纯文本台账，每行一条，`音频编号<TAB>文本`，编号与音频一一对应
            transcript_lines.append(f"{row['recordingId']}\t{row['text']}")
            manifest["items"].append(
                {
                    "recordingId": row["recordingId"],
                    "file": row["file"],
                    "md5": hashlib.md5(data).hexdigest(),
                    "text": row["text"],
                    "collector": row["collector"],
                }
            )
        # metadata.csv / transcripts.txt 一律 UTF-8 无 BOM（供下游程序解析）
        z.writestr("metadata.csv", csv_buf.getvalue())
        z.writestr(
            "transcripts.txt",
            "\n".join(transcript_lines) + ("\n" if transcript_lines else ""),
        )
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    # 2) 数量一致性复核：ZIP 内音频条目数必须等于台账行数（§6.1）
    with zipfile.ZipFile(buf) as zf:
        n_audio = sum(1 for n in zf.namelist() if n.startswith("audio/"))
    if n_audio != len(rows):
        raise ValueError(
            f"导出中止：ZIP 内音频文件数({n_audio})与台账记录数({len(rows)})不一致"
        )

    buf.seek(0)
    return buf


async def _run_export_job(job_id: str, rows: list[dict]) -> None:
    """后台打包任务：完成后写入对象存储并更新 ExportJob 记录（自带会话，独立于请求）。"""
    async with SessionLocal() as db:
        try:
            buf = await _build_export_zip(rows)
            key = f"exports/{job_id}.zip"
            await storage.save(key, buf.getvalue())
            job = await db.get(models.ExportJob, job_id)
            job.status = "done"
            job.key = key
            job.total = len(rows)
            job.finished_at = models.utcnow()
            await db.commit()
            # 顺带清理超期导出包（方案 §6.2），失败不影响本次导出
            try:
                await purge_expired_exports(db)
            except Exception:
                pass
        except Exception as e:  # 含 §6.1 完整性校验失败：记入任务表，便于前端排查
            job = await db.get(models.ExportJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(e)
                job.finished_at = models.utcnow()
                await db.commit()


@router.post("/admin/export")
async def export_dataset(principal=Depends(require_reviewer), db=Depends(get_db)):
    """导出已通过录音（方案 §6）。

    - 数量 ≤ 阈值：同步流式返回 zip。
    - 数量 > 阈值：异步打包，写入 ExportJob（持久化），返回 jobId 供前端轮询。
    - 完整性校验失败（音频缺失 / 数量不一致）→ 中止导出并说明原因（§6.1）。
    """
    rows = await _collect_export_rows(db)

    if len(rows) > EXPORT_ASYNC_THRESHOLD:
        job_id = uuid.uuid4().hex
        db.add(models.ExportJob(job_id=job_id, status="pending", total=len(rows)))
        await db.commit()
        asyncio.create_task(_run_export_job(job_id, rows))
        record_audit(
            db,
            principal["uid"],
            principal["role"],
            "export_async_start",
            "dataset",
            f"job={job_id};count={len(rows)}",
        )
        await db.commit()
        return ok(
            {
                "async": True,
                "jobId": job_id,
                "total": len(rows),
                "status": "pending",
                "pollUrl": f"/api/admin/export/{job_id}",
            }
        )

    try:
        buf = await _build_export_zip(rows)
    except ValueError as e:  # §6.1 一致性校验未通过
        return fail(str(e))

    record_audit(
        db,
        principal["uid"],
        principal["role"],
        "export",
        "dataset",
        f"count={len(rows)}",
    )
    await db.commit()
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=dataset.zip"},
    )


@router.get("/admin/export/jobs")
async def list_export_jobs(
    limit: int = Query(20, ge=1, le=100),
    principal=Depends(require_reviewer),
    db=Depends(get_db),
):
    """导出任务列表（含留存到期时间），供管理端查看历史导出与清理结果。"""
    rows = await db.execute(
        select(models.ExportJob).order_by(models.ExportJob.created_at.desc()).limit(limit)
    )
    ttl = settings.export_ttl_days
    items = []
    for j in rows.scalars():
        expires_at = ""
        if j.status == "done" and j.finished_at and ttl > 0:
            expires_at = (j.finished_at + timedelta(days=ttl)).isoformat()
        items.append(
            {
                "jobId": j.job_id,
                "status": j.status,
                "total": j.total,
                "error": j.error or "",
                "createdAt": j.created_at.isoformat() if j.created_at else "",
                "finishedAt": j.finished_at.isoformat() if j.finished_at else "",
                "expiresAt": expires_at,
            }
        )
    return ok({"list": items, "ttlDays": ttl})


@router.post("/admin/export/cleanup")
async def cleanup_exports(principal=Depends(require_admin), db=Depends(get_db)):
    """手动清理超期导出文件（方案 §6.2）。服务启动与每次异步导出后也会自动执行。"""
    stats = await purge_expired_exports(db)
    record_audit(
        db,
        principal["uid"],
        principal["role"],
        "export_cleanup",
        "dataset",
        "exports",
        {
            "ttlDays": stats["ttlDays"],
            "expiredJobs": stats["expiredJobs"],
            "deletedFiles": stats["deletedFiles"],
            "orphans": stats["orphans"],
        },
    )
    await db.commit()
    return ok(stats)


@router.get("/admin/export/{job_id}")
async def export_job_status(job_id: str, principal=Depends(require_reviewer), db=Depends(get_db)):
    """导出任务状态查询；完成返回签名下载 URL。"""
    job = await db.get(models.ExportJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status == "done" and job.key:
        url = await storage.url(job.key)
        return ok({"status": "done", "url": url, "total": job.total})
    if job.status == "failed":
        return ok({"status": "failed", "error": job.error, "total": job.total})
    return ok({"status": job.status, "total": job.total})


@router.get("/admin/users")
async def list_users(principal=Depends(require_admin), db=Depends(get_db)):
    """列出用户及其角色，供管理端分配权限。"""
    rows = await db.execute(select(models.User).order_by(models.User.id))
    items = [
        {"userId": u.user_id, "openid": u.openid, "role": u.role} for u in rows.scalars()
    ]
    return ok({"list": items})


@router.post("/admin/users/{user_id}/role")
async def set_user_role(
    user_id: str, request: Request, principal=Depends(require_admin), db=Depends(get_db)
):
    """设置用户角色（仅管理员可调）。角色须为允许值。"""
    body = await request.json()
    new_role = (body or {}).get("role", "")
    if new_role not in ALLOWED_ROLES:
        return {"code": 1, "message": f"角色须为 {sorted(ALLOWED_ROLES)}", "data": None}

    user = await db.scalar(select(models.User).where(models.User.user_id == user_id))
    if not user:
        raise HTTPException(404, "用户不存在")
    old_role = user.role
    user.role = new_role
    record_audit(
        db, principal["uid"], principal["role"], "set_role", "user", user_id,
        {"from": old_role, "to": new_role},
    )
    await db.commit()
    return ok({"userId": user_id, "role": new_role})
