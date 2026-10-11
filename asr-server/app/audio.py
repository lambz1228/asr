"""音频处理：探测真实参数、转码为 WAV、质量分析。

关键原则（见方案第 3 节）：微信原生只出 aac/mp3，WAV 在这里转码；
转码按【原始采样率】进行，绝不向上采样到 48kHz（上采样不提升音质）。
"""
import array
import asyncio
import json
import math
import os
import tempfile
import wave

from .config import settings


async def _run(cmd: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='ignore')[:300]}")
    return out.decode(errors="ignore")


async def probe(path: str) -> dict:
    """用 ffprobe 取真实编码/采样率/声道/时长。"""
    out = await _run(
        [
            settings.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            path,
        ]
    )
    info = json.loads(out)
    stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {}
    )
    fmt = info.get("format", {})
    dur = fmt.get("duration") or stream.get("duration")
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        "channels": int(stream["channels"]) if stream.get("channels") else None,
        "duration": float(dur) if dur else None,
    }


async def transcode_to_wav(src: str, dst: str, target_sr: int | None = None) -> None:
    """转码为单声道 WAV。target_sr 为空时保留原始采样率（不上采样）。"""
    cmd = [settings.ffmpeg_path, "-y", "-i", src, "-ac", "1"]
    if target_sr:
        cmd += ["-ar", str(target_sr)]
    cmd.append(dst)
    await _run(cmd)


def analyze_wav(path: str) -> dict:
    """读取 16-bit PCM，计算音量(RMS)、削波比例、静音比例。"""
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        fr = w.getframerate()
        raw = w.readframes(w.getnframes())

    if sw != 2:
        return {
            "rms_db": None,
            "clipping_ratio": None,
            "silence_ratio": None,
            "sample_rate": fr,
            "note": "non-16bit, skipped analysis",
        }

    samples = array.array("h")
    samples.frombytes(raw)
    if nch == 2:
        samples = samples[::2]  # 取单声道分析

    total = len(samples)
    if total == 0:
        return {"rms_db": -100.0, "clipping_ratio": 0.0, "silence_ratio": 1.0, "sample_rate": fr}

    sq = sum(s * s for s in samples)
    rms = math.sqrt(sq / total)
    rms_db = 20 * math.log10(rms / 32768) if rms > 0 else -100.0
    clip = sum(1 for s in samples if abs(s) >= 32767)
    sil_thr = int(0.01 * 32768)
    sil = sum(1 for s in samples if abs(s) < sil_thr)

    return {
        "rms_db": round(rms_db, 2),
        "clipping_ratio": round(clip / total, 5),
        "silence_ratio": round(sil / total, 4),
        "sample_rate": fr,
    }


def quality_flags(m: dict) -> list[str]:
    """按方案 5.2 阈值映射质量标记（仅作警告，不阻断提交）。"""
    flags: list[str] = []
    if m.get("rms_db") is not None and m["rms_db"] < -30:
        flags.append("low_volume")
    if m.get("clipping_ratio") is not None and m["clipping_ratio"] > 0.001:
        flags.append("clipping")
    if m.get("silence_ratio") is not None and m["silence_ratio"] > 0.3:
        flags.append("too_much_silence")
    return flags


async def process_upload(raw_bytes: bytes, ext: str) -> dict:
    """完整流水线：落临时文件 → 探测 → 转码 WAV → 质量分析。返回处理结果与字节。"""
    result: dict = {
        "probe": {},
        "transcode_status": "skipped",
        "wav_bytes": None,
        "quality_flags": [],
        "metrics": {},
    }
    if not settings.ffmpeg_enabled:
        return result

    tmp_dir = tempfile.mkdtemp(prefix="asr_")
    src = os.path.join(tmp_dir, f"src.{ext}")
    dst = os.path.join(tmp_dir, "out.wav")
    with open(src, "wb") as f:
        f.write(raw_bytes)

    try:
        result["probe"] = await probe(src)
        await transcode_to_wav(src, dst)  # 保留原始采样率
        with open(dst, "rb") as f:
            result["wav_bytes"] = f.read()
        # analyze_wav 是纯 Python 的逐样本循环（受 GIL 约束），必须放到线程池执行。
        # 直接 await 调用会占住事件循环：实测 44.1kHz/60s 需 0.5s，48kHz/300s 需 2.6s，
        # 这期间整个服务（所有人的所有请求）都被冻住。20 人同时上传时表现为集体卡顿。
        result["metrics"] = await asyncio.to_thread(analyze_wav, dst)
        result["quality_flags"] = quality_flags(result["metrics"])
        result["transcode_status"] = "done"
    except Exception as e:  # ffmpeg 缺失或解析失败不应中断上传
        result["transcode_status"] = "failed"
        result["error"] = str(e)
    finally:
        for p in (src, dst):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
    return result
