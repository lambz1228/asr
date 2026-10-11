#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机录音参数验证 —— 主机侧带跑脚本

配合《真机录音参数验证清单.md》使用。两条数据来源：

1) --dir <目录>   离线：扫描目录里的真机导出音频（aac/mp3/wav/m4a）。
                  优先用 ffprobe 复核；本机无 ffprobe 时，用内置解析器
                  （WAV(RIFF) / ADTS-AAC 头 / MP3 帧头）做零依赖检测。
2) --api <baseUrl>  在线：从后端 dev 接口拉取端侧探针上报记录
                  （GET /api/dev/audio-probe，后端需 ENV=dev），
                  自动按「机型 × 参数」聚合出验证矩阵。

对每项按期望参数判定：格式 / 采样率 / 声道 一致为 PASS，否则 CHECK 并给出说明。
输出（默认写到 E:/asr/，可用 --out-dir 改）：
  - 真机录音验证报告.md
  - verification_matrix.csv

用法示例：
  # 离线：扫描真机导出目录，基准期望 aac/16000/1
  python verify_recording.py --dir ./samples --expect-format aac --expect-sample-rate 16000 --expect-channels 1

  # 在线：从 dev 后端拉取端侧上报记录（每项期望取自各自上报的 req*）
  python verify_recording.py --api http://localhost:8000/api --token <JWT>

  # 指定 ffprobe 路径（否则自动在 PATH 中查找）
  python verify_recording.py --dir ./samples --ffprobe "C:/ffmpeg/bin/ffprobe.exe"
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import wave
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

AUDIO_EXTS = {".aac", ".mp3", ".wav", ".m4a", ".caf"}
# ADTS sampling_frequency_index -> Hz
ADTS_SR = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350]
# MP3 版本 -> 采样率表（version: 3=MPEG1, 2=MPEG2, 0=MPEG2.5）
MP3_SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


# --------------------------------------------------------------------------- #
# 检测：ffprobe（权威） + 内置解析（零依赖）
# --------------------------------------------------------------------------- #
def which_ffprobe(explicit=None):
    if explicit:
        return explicit if (os.path.exists(explicit) or shutil.which(explicit)) else None
    return shutil.which("ffprobe")


def ffprobe_detect(path, ffprobe_bin):
    try:
        out = subprocess.run(
            [ffprobe_bin, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        info = json.loads(out.stdout or "{}")
    except Exception:
        return None
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = info.get("format", {})
    dur = fmt.get("duration") or stream.get("duration")
    br = fmt.get("bit_rate") or stream.get("bit_rate")
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        "channels": int(stream["channels"]) if stream.get("channels") else None,
        "duration": round(float(dur), 3) if dur else None,
        "bitrate_kbps": round(float(br) / 1000, 1) if br else None,
        "method": "ffprobe",
    }


def parse_wav(path):
    try:
        with wave.open(path, "rb") as w:
            sr = w.getframerate()
            ch = w.getnchannels()
            frames = w.getnframes()
            sw = w.getsampwidth()
        return {
            "codec": f"pcm_s{sw * 8}le",
            "sample_rate": sr,
            "channels": ch,
            "duration": round(frames / sr, 3) if sr else None,
        }
    except Exception:
        return None


def parse_adts_aac(data):
    """解析 ADTS-AAC 头：同步字 0xFFF + sampling_frequency_index + channel_configuration。"""
    n = len(data)
    i = 0
    while i + 7 <= n and not (data[i] == 0xFF and (data[i + 1] & 0xF0) == 0xF0):
        i += 1
    if i + 7 > n:
        return None
    sr_idx = (data[i + 2] >> 2) & 0x0F
    ch = ((data[i + 2] & 0x01) << 2) | ((data[i + 3] >> 6) & 0x03)
    sr = ADTS_SR[sr_idx] if sr_idx < len(ADTS_SR) else None
    return {"codec": "aac", "sample_rate": sr, "channels": ch or None, "duration": None}


def parse_mp3(data):
    """解析 MP3 帧头（跳过 ID3v2）：版本 + 采样率索引 + 声道模式。"""
    n = len(data)
    i = 0
    if data[:3] == b"ID3" and n > 10:
        sz = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        i = 10 + sz
    while i + 4 <= n and not (data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0):
        i += 1
    if i + 4 > n:
        return None
    h = data[i:i + 4]
    ver = (h[1] >> 3) & 0x03
    sr_idx = (h[2] >> 2) & 0x03
    ch_mode = (h[3] >> 6) & 0x03
    sr = MP3_SR[ver][sr_idx] if (sr_idx != 3 and ver in MP3_SR) else None
    ch = 1 if ch_mode == 3 else 2
    return {"codec": "mp3", "sample_rate": sr, "channels": ch, "duration": None}


def detect_file(path, ffprobe_bin=None):
    size = os.path.getsize(path)
    if ffprobe_bin:
        r = ffprobe_detect(path, ffprobe_bin)
        if r:
            r["size_bytes"] = size
            if not r.get("bitrate_kbps") and r.get("duration"):
                r["bitrate_kbps"] = round(size * 8 / r["duration"] / 1000, 1)
            return r

    with open(path, "rb") as f:
        head = f.read(65536)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    has2 = len(head) >= 2
    is_ff = has2 and head[0] == 0xFF
    r = None
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        r = parse_wav(path)
    elif head[:3] == b"ID3":
        # ID3 头基本确定为 MP3
        r = parse_mp3(head)
    elif is_ff and (head[1] & 0xF0) == 0xF0:
        # 0xFFF（12 位同步）：ADTS-AAC 的 layer 字段恒为 00，MP3 的 layer 非 00，借此区分
        layer = (head[1] >> 1) & 0x03
        r = parse_adts_aac(head) if layer == 0 else parse_mp3(head)
    elif is_ff and (head[1] & 0xE0) == 0xE0:
        r = parse_mp3(head)
    elif ext == "aac":
        r = parse_adts_aac(head)
    elif ext == "mp3":
        r = parse_mp3(head)
    if r is None:
        r = {"codec": None, "sample_rate": None, "channels": None, "duration": None}
    r["size_bytes"] = size
    r.setdefault("method", "builtin")
    r.setdefault("bitrate_kbps", None)
    if r.get("duration") and not r.get("bitrate_kbps"):
        r["bitrate_kbps"] = round(size * 8 / r["duration"] / 1000, 1)
    return r


# --------------------------------------------------------------------------- #
# 判定
# --------------------------------------------------------------------------- #
def judge(det, expect):
    issues = []
    codec, sr, ch = det.get("codec"), det.get("sample_rate"), det.get("channels")
    if expect.get("format"):
        if codec is None:
            issues.append("未能识别格式/编码")
        elif codec != expect["format"]:
            issues.append(f"格式 {codec} != 期望 {expect['format']}")
    if expect.get("sample_rate") and sr and sr != expect["sample_rate"]:
        issues.append(f"采样率 {sr} != 期望 {expect['sample_rate']}")
    if expect.get("channels") and ch and ch != expect["channels"]:
        issues.append(f"声道 {ch} != 期望 {expect['channels']}")
    return ("PASS" if not issues else "CHECK", issues)


def make_row(det, expect, verdict, issues, source, name="", device="", reporter=""):
    return {
        "name": name,
        "source": source,
        "device": device,
        "reporter": reporter,
        "expect_format": expect.get("format", ""),
        "expect_sample_rate": expect.get("sample_rate", ""),
        "expect_channels": expect.get("channels", ""),
        "det_codec": det.get("codec"),
        "det_sample_rate": det.get("sample_rate"),
        "det_channels": det.get("channels"),
        "det_duration": det.get("duration"),
        "size_bytes": det.get("size_bytes"),
        "bitrate_kbps": det.get("bitrate_kbps"),
        "method": det.get("method"),
        "verdict": verdict,
        "issues": "; ".join(issues),
    }


# --------------------------------------------------------------------------- #
# 数据来源
# --------------------------------------------------------------------------- #
def run_dir(d, expect, ffprobe_bin):
    rows = []
    if not os.path.isdir(d):
        raise SystemExit(f"[ERR] 目录不存在: {d}")
    files = sorted(f for f in os.listdir(d) if os.path.splitext(f)[1].lower() in AUDIO_EXTS)
    if not files:
        raise SystemExit(f"[ERR] 目录内无音频文件: {d}")
    for fn in files:
        det = detect_file(os.path.join(d, fn), ffprobe_bin)
        verdict, issues = judge(det, expect)
        rows.append(make_row(det, expect, verdict, issues, source="file", name=fn))
    return rows


def fetch_api(base_url, token):
    url = base_url.rstrip("/") + "/dev/audio-probe"
    headers = {"Authorization": "Bearer " + token} if token else {}
    req = urllib.request.Request(url, headers=headers)
    # 本机地址绕过系统代理，避免被代理劫持（502）
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        resp_cm = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30)
    else:
        resp_cm = urllib.request.urlopen(req, timeout=30)
    with resp_cm as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("data", [])


def rows_from_api(records, default_expect):
    rows = []
    for rec in records:
        expect = {
            "format": rec.get("reqFormat") or default_expect.get("format"),
            "sample_rate": rec.get("reqSampleRate") or default_expect.get("sample_rate"),
            "channels": rec.get("reqChannels") or default_expect.get("channels"),
        }
        # 服务端 ffprobe 权威值优先；缺失则用端侧 headerGuess 粗判
        codec = rec.get("realCodec") or (rec.get("headerGuess") if rec.get("headerGuess") in ("aac", "mp3") else None)
        det = {
            "codec": codec,
            "sample_rate": rec.get("realSampleRate"),
            "channels": rec.get("realChannels"),
            "duration": rec.get("realDuration") or rec.get("duration"),
            "size_bytes": rec.get("sizeBytes"),
            "bitrate_kbps": rec.get("estBitrateKbps"),
            "method": "ffprobe" if rec.get("realCodec") else "端侧估算",
        }
        verdict, issues = judge(det, expect)
        if rec.get("decoded") is False:
            issues.append("服务端解码失败")
            verdict = "CHECK"
        rows.append(make_row(
            det, expect, verdict, issues,
            source="api", name="", device=rec.get("device", ""), reporter=rec.get("reporter", ""),
        ))
    return rows


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def _v(x):
    return "-" if x is None else str(x)


def write_outputs(rows, out_dir, source_desc, expect):
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rep = ["# 真机录音参数验证报告\n"]
    rep.append(f"- 生成时间：{ts}")
    rep.append(f"- 数据来源：{source_desc}")
    rep.append(
        f"- 默认期望：format={expect.get('format') or '-'} / "
        f"sampleRate={expect.get('sample_rate') or '-'} / channels={expect.get('channels') or '-'}\n"
    )
    rep.append("## 汇总矩阵\n")
    rep.append("| # | 文件/设备 | 期望(fmt/rate/ch) | 实测(codec/rate/ch/dur) | 大小 | 码率 | 检测 | 判定 | 说明 |")
    rep.append("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        who = r["name"] or r["device"] or "?"
        exp = f"{r['expect_format'] or '-'}/{_v(r['expect_sample_rate'])}/{_v(r['expect_channels'])}"
        det = f"{_v(r['det_codec'])}/{_v(r['det_sample_rate'])}/{_v(r['det_channels'])}/{_v(r['det_duration'])}"
        kb = f"{r['size_bytes'] / 1024:.1f}KB" if r["size_bytes"] else "-"
        br = f"{r['bitrate_kbps']:.1f}kbps" if isinstance(r["bitrate_kbps"], (int, float)) else "-"
        rep.append(f"| {i} | {who} | {exp} | {det} | {kb} | {br} | {r['method']} | {r['verdict']} | {r['issues']} |")

    npass = sum(1 for r in rows if r["verdict"] == "PASS")
    nchk = len(rows) - npass
    rep.append("\n## 结论\n")
    rep.append(f"- 共 {len(rows)} 项：**通过 {npass} 项**，**待核 {nchk} 项**。")
    if nchk:
        rep.append("- 待核项优先核对：")
        for r in rows:
            if r["verdict"] != "PASS":
                who = r["name"] or r["device"] or "?"
                rep.append(f"  - `{who}`：{r['issues'] or '未知原因'}")
    rep.append(
        "\n> 提示：采样率/声道与期望不一致时，若为「48k 探测项（V4）」或「双声道项（V6）」，"
        "通常说明设备/基础库不支持该配置——按清单要求记录为「不可用」，并回到业务侧确认是否下调指标。"
    )
    rep.append(
        "\n> 交叉验证：端侧 `headerGuess` 仅嗅探文件头，真实采样率/声道以 ffprobe（服务端或本机）为准。"
        "若两处结论冲突，以 ffprobe 为准。"
    )

    report_path = os.path.join(out_dir, "真机录音验证报告.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")

    csv_path = os.path.join(out_dir, "verification_matrix.csv")
    fields = list(rows[0].keys()) if rows else []
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    return report_path, csv_path, npass, nchk


# --------------------------------------------------------------------------- #
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.dirname(here)  # E:/asr/

    ap = argparse.ArgumentParser(description="真机录音参数验证 - 主机侧带跑脚本")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dir", help="离线：扫描真机导出音频目录")
    src.add_argument("--api", help="在线：后端 dev 接口 baseUrl，如 http://localhost:8000/api")
    ap.add_argument("--token", default="", help="在线模式：登录 JWT（Authorization: Bearer）")
    ap.add_argument("--ffprobe", default=None, help="ffprobe 可执行路径（默认在 PATH 查找）")
    ap.add_argument("--expect-format", default="aac", help="期望格式（默认 aac；可 mp3/空）")
    ap.add_argument("--expect-sample-rate", type=int, default=16000, help="期望采样率（默认 16000；0 表示不校验）")
    ap.add_argument("--expect-channels", type=int, default=1, help="期望声道（默认 1；0 表示不校验）")
    ap.add_argument("--out-dir", default=default_out, help="输出目录（默认 E:/asr/）")
    args = ap.parse_args()

    default_expect = {
        "format": args.expect_format or "",
        "sample_rate": args.expect_sample_rate or "",
        "channels": args.expect_channels or "",
    }

    if args.dir:
        ffprobe_bin = which_ffprobe(args.ffprobe)
        rows = run_dir(args.dir, default_expect, ffprobe_bin)
        source_desc = f"离线扫描 `{os.path.abspath(args.dir)}`（检测方式：{'ffprobe' if ffprobe_bin else '内置解析器'}）"
    else:
        if not args.token:
            print("[WARN] 未提供 --token，接口若需鉴权将返回 401。", file=sys.stderr)
        records = fetch_api(args.api, args.token)
        rows = rows_from_api(records, default_expect)
        source_desc = f"在线拉取 `{args.api}/dev/audio-probe`（共 {len(records)} 条记录）"
        if not records:
            raise SystemExit("[ERR] 后端无探测记录：请先在真机用探针上报（ENV=dev）。")

    report_path, csv_path, npass, nchk = write_outputs(rows, args.out_dir, source_desc, default_expect)

    print(f"[OK] 共 {len(rows)} 项：通过 {npass}，待核 {nchk}")
    print(f"[OK] 报告: {report_path}")
    print(f"[OK] 矩阵: {csv_path}")


if __name__ == "__main__":
    main()
