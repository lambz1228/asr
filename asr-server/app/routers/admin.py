import asyncio
import csv
import hashlib
import io
import json
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from .. import models
from ..db import SessionLocal
from ..deps import require_admin, get_db, record_audit
from ..responses import ok
from ..schemas import ReviewPayload
from ..storage import storage

router = APIRouter()

# 超过该阈值时导出改为异步任务（避免长请求阻塞 + 便于大批量流式打包）
EXPORT_ASYNC_THRESHOLD = 1000

# 允许分配的角色
ALLOWED_ROLES = {"collector", "reviewer", "admin"}


@router.get("/admin/audios")
async def list_audios(principal=Depends(require_admin), db=Depends(get_db)):
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
    principal=Depends(require_admin),
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


async def _build_export_zip(recs) -> io.BytesIO:
    """构造 dataset.zip = audio/ + metadata.csv + manifest.json。"""
    buf = io.BytesIO()
    manifest = {"total": len(recs), "items": []}
    csv_lines = io.StringIO()
    writer = csv.writer(csv_lines)
    writer.writerow(
        [
            "recordingId",
            "assignmentId",
            "version",
            "sampleRate",
            "channels",
            "codec",
            "duration",
            "qualityFlags",
            "status",
        ]
    )

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in recs:
            key = r.wav_key or r.raw_key
            data = b""
            if key:
                try:
                    data = await storage.read(key)
                except Exception:
                    data = b""
            ext = "wav" if r.wav_key else (key.rsplit(".", 1)[-1] if key else "bin")
            fname = f"audio/{r.recording_id}.{ext}"
            z.writestr(fname, data)
            md5 = hashlib.md5(data).hexdigest() if data else ""
            writer.writerow(
                [
                    r.recording_id,
                    r.assignment_id,
                    r.version,
                    r.real_sample_rate,
                    r.real_channels,
                    r.real_codec,
                    r.duration,
                    ",".join(r.quality_flags or []),
                    r.status,
                ]
            )
            manifest["items"].append(
                {"recordingId": r.recording_id, "file": fname, "md5": md5}
            )
        z.writestr("metadata.csv", csv_lines.getvalue())
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    return buf


async def _run_export_job(job_id: str, recs) -> None:
    """后台打包任务：完成后写入对象存储并更新 ExportJob 记录（自带会话，独立于请求）。"""
    from ..models import utcnow

    async with SessionLocal() as db:
        try:
            buf = await _build_export_zip(recs)
            key = f"exports/{job_id}.zip"
            await storage.save(key, buf.getvalue())
            job = await db.get(models.ExportJob, job_id)
            job.status = "done"
            job.key = key
            job.total = len(recs)
            job.finished_at = utcnow()
            await db.commit()
        except Exception as e:  # 记入任务表，便于前端排查
            job = await db.get(models.ExportJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(e)
                job.finished_at = utcnow()
                await db.commit()


@router.post("/admin/export")
async def export_dataset(principal=Depends(require_admin), db=Depends(get_db)):
    """导出已通过录音。

    - 数量 ≤ 阈值：同步流式返回 zip。
    - 数量 > 阈值：异步打包，写入 ExportJob（持久化），返回 jobId 供前端轮询。
    """
    rows = await db.execute(
        select(models.Recording).where(models.Recording.status == "approved")
    )
    recs = rows.scalars().all()

    if len(recs) > EXPORT_ASYNC_THRESHOLD:
        job_id = uuid.uuid4().hex
        db.add(models.ExportJob(job_id=job_id, status="pending", total=len(recs)))
        await db.commit()
        asyncio.create_task(_run_export_job(job_id, recs))
        record_audit(
            db,
            principal["uid"],
            principal["role"],
            "export_async_start",
            "dataset",
            f"job={job_id};count={len(recs)}",
        )
        await db.commit()
        return ok(
            {
                "async": True,
                "jobId": job_id,
                "total": len(recs),
                "status": "pending",
                "pollUrl": f"/api/admin/export/{job_id}",
            }
        )

    record_audit(
        db,
        principal["uid"],
        principal["role"],
        "export",
        "dataset",
        f"count={len(recs)}",
    )
    await db.commit()
    buf = await _build_export_zip(recs)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=dataset.zip"},
    )


@router.get("/admin/export/{job_id}")
async def export_job_status(job_id: str, principal=Depends(require_admin), db=Depends(get_db)):
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
