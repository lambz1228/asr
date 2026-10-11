"""开发态验证接口（仅 ENV=dev 装配）：真机录音参数验证。

用途（对应《真机录音参数验证清单.md》与方案第 3.2 节）：
- 端侧探针在真机上探测一段录音后，把「请求配置 + 文件客观量」上报到 `POST /api/dev/audio-probe`；
  若同时带上音频文件，服务端用 ffprobe 复核真实 codec / 采样率 / 声道 / 时长（权威值）。
- 主机侧带跑脚本 `tools/verify_recording.py` 通过 `GET /api/dev/audio-probe` 拉取全部记录，
  聚合出「机型 × 参数组合」的验证矩阵与通过/风险判定。

这些接口不参与业务链路，生产不装配。
"""
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select

from .. import models
from ..audio import probe as ffprobe_probe
from ..config import settings
from ..deps import get_current_user, get_db
from ..responses import ok
from ..storage import storage

router = APIRouter()


async def _ffprobe_bytes(data: bytes, ext: str) -> dict:
    """把上传字节落临时文件后 ffprobe 复核；ffmpeg 不可用或失败返回 {}。"""
    if not settings.ffmpeg_enabled:
        return {}
    tmp_dir = tempfile.mkdtemp(prefix="probe_")
    path = os.path.join(tmp_dir, f"probe.{ext}")
    try:
        with open(path, "wb") as f:
            f.write(data)
        return await ffprobe_probe(path)
    except Exception:
        return {}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


@router.post("/dev/audio-probe")
async def create_audio_probe(
    device: str = Form(""),
    wechat_ver: str = Form("", alias="wechatVer"),
    req_format: str = Form("", alias="reqFormat"),
    req_sample_rate: int = Form(0, alias="reqSampleRate"),
    req_channels: int = Form(0, alias="reqChannels"),
    size_bytes: int = Form(0, alias="sizeBytes"),
    duration: float = Form(0.0),
    est_bitrate_kbps: float = Form(0.0, alias="estBitrateKbps"),
    header_guess: str = Form("", alias="headerGuess"),
    file: UploadFile | None = File(None),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    probe_id = "p_" + uuid.uuid4().hex[:10]
    file_key = None
    real: dict = {}

    if file is not None:
        data = await file.read()
        ext = (file.filename or "aac").rsplit(".", 1)[-1].lower()
        if ext not in ("aac", "mp3", "wav", "m4a"):
            ext = "aac"
        file_key = f"probe/{probe_id}.{ext}"
        await storage.save(file_key, data)
        if not size_bytes:
            size_bytes = len(data)
        real = await _ffprobe_bytes(data, ext)

    decoded = None
    if real:
        decoded = real.get("codec") is not None

    row = models.AudioProbe(
        probe_id=probe_id,
        reporter=user["uid"],
        device=device,
        wechat_ver=wechat_ver,
        req_format=req_format,
        req_sample_rate=req_sample_rate,
        req_channels=req_channels,
        size_bytes=size_bytes,
        duration=duration,
        est_bitrate_kbps=est_bitrate_kbps,
        header_guess=header_guess,
        real_codec=real.get("codec"),
        real_sample_rate=real.get("sample_rate"),
        real_channels=real.get("channels"),
        real_duration=real.get("duration"),
        decoded=decoded,
        file_key=file_key,
    )
    db.add(row)
    await db.commit()

    return ok(
        {
            "probeId": probe_id,
            "real": {
                "codec": row.real_codec,
                "sampleRate": row.real_sample_rate,
                "channels": row.real_channels,
                "duration": row.real_duration,
            },
            "decoded": decoded,
            "note": "服务端 ffprobe 复核为权威值；未开启 ffmpeg 时 real 为空，以端侧 headerGuess 作粗判",
        }
    )


@router.get("/dev/audio-probe")
async def list_audio_probes(user=Depends(get_current_user), db=Depends(get_db)):
    rows = (
        await db.execute(select(models.AudioProbe).order_by(models.AudioProbe.id.asc()))
    ).scalars().all()
    return ok(
        [
            {
                "probeId": r.probe_id,
                "reporter": r.reporter,
                "device": r.device,
                "wechatVer": r.wechat_ver,
                "reqFormat": r.req_format,
                "reqSampleRate": r.req_sample_rate,
                "reqChannels": r.req_channels,
                "sizeBytes": r.size_bytes,
                "duration": r.duration,
                "estBitrateKbps": r.est_bitrate_kbps,
                "headerGuess": r.header_guess,
                "realCodec": r.real_codec,
                "realSampleRate": r.real_sample_rate,
                "realChannels": r.real_channels,
                "realDuration": r.real_duration,
                "decoded": r.decoded,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    )
