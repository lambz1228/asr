import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from .. import models
from ..audio import process_upload
from ..config import settings
from ..deps import require_voice_consent, get_db, record_audit
from ..responses import ok
from ..storage import storage

router = APIRouter()


@router.post("/tasks/{task_id}/upload")
async def upload_audio(
    task_id: str,
    file: UploadFile = File(...),
    text_id: str = Form("", alias="textId"),
    upload_id: str = Form("", alias="uploadId"),
    principal=Depends(require_voice_consent),
    db=Depends(get_db),
):
    # 1) uploadId 防重：重复提交直接返回已上传，不重复落库
    if upload_id:
        existing = await db.scalar(
            select(models.Recording).where(models.Recording.upload_id == upload_id)
        )
        if existing:
            return ok(
                {
                    "status": "uploaded",
                    "audioId": existing.recording_id,
                    "transcode": existing.transcode_status,
                    "qualityFlags": existing.quality_flags,
                }
            )

    raw = await file.read()
    ext = (file.filename or "aac").rsplit(".", 1)[-1].lower()
    if ext not in ("aac", "mp3", "wav", "m4a"):
        ext = "aac"

    # 2) 保存原始音频（对象存储）
    raw_key = f"raw/{task_id}/{upload_id}.{ext}"
    await storage.save(raw_key, raw)

    # 3) FFmpeg 探测 + 转码 WAV（按原始采样率）+ 质量分析
    probe: dict = {}
    flags: list = []
    metrics: dict = {}
    wav_key = None
    tstatus = "skipped"
    if settings.ffmpeg_enabled:
        proc = await process_upload(raw, ext)
        tstatus = proc["transcode_status"]
        probe = proc["probe"]
        metrics = proc["metrics"]
        flags = proc["quality_flags"]
        if proc["wav_bytes"]:
            wav_key = f"wav/{task_id}/{upload_id}.wav"
            await storage.save(wav_key, proc["wav_bytes"])

    # 4) 关联任务并计算录音版本：退回重录递增，历史版本全部保留（方案 §10.2）
    asg = await db.scalar(
        select(models.TaskAssignment).where(
            models.TaskAssignment.assignment_id == task_id
        )
    )
    version = (asg.version + 1) if asg else 1

    # 5) 落库：录音版本 + 关联任务
    rec_id = "r_" + uuid.uuid4().hex[:10]
    rec = models.Recording(
        recording_id=rec_id,
        assignment_id=task_id,
        upload_id=upload_id,
        version=version,
        raw_key=raw_key,
        wav_key=wav_key,
        real_sample_rate=probe.get("sample_rate"),
        real_channels=probe.get("channels"),
        real_codec=probe.get("codec"),
        duration=probe.get("duration"),
        quality_flags=flags,
        transcode_status=tstatus,
        status="uploaded",
    )
    db.add(rec)

    # 6) 更新任务状态 / 版本
    if asg:
        asg.version = version
        asg.status = "uploaded"

    record_audit(
        db,
        principal["uid"],
        principal["role"],
        "upload",
        "recording",
        rec_id,
        {"quality_flags": flags, "probe": probe},
    )
    await db.commit()

    return ok(
        {
            "status": "uploaded",
            "audioId": rec_id,
            "transcode": tstatus,
            "qualityFlags": flags,
            "probe": probe,
        }
    )
