# -*- coding: utf-8 -*-
"""
为 ASR 语音采集小程序的介绍视频生成中文配音。

用法：
    python gen_voiceover.py

产物：audio/s0.wav ... s4.wav（16-bit PCM，单声道）
     顺序与 config.js 的 scenes 一一对应。
依赖：edge-tts（托管 venv 已装）+ skill 自带的 ffmpeg-static。
"""
import asyncio
import os
import subprocess
import sys

import edge_tts

VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "+0%"

FFMPEG = (
    r"C:\Users\Admin（无密码）\.workbuddy\skills\project-intro-video"
    r"\node_modules\ffmpeg-static\ffmpeg.exe"
)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "audio")

# 与 config.js 的 scenes 顺序一致：intro / pain / feature / usage / cta
LINES = [
    "这是一个语音数据采集小程序，让数据集生产，从三周缩短到三天。",
    "语音采集常卡在三件事上：任务散落各处，逐人派发耗时又容易漏；"
    "噪声和打断没人察觉，交上来才发现要返工；进度只能靠反复追问、手工统计。",
    "现在，一套小程序跑通全流程：上传 Excel，按人拆成子任务；"
    "照文本队列式录制，支持暂停和重录；在线试听审核，一键导出标准数据集。",
    "三步就能跑通：管理员导入任务，Excel 两列即可；"
    "采集员照文本逐条录制；审核员试听通过，导出标准数据集。",
    "把语音数据集生产，交给一套系统。微信搜索小程序，登录即可开始。",
]


async def synth(i: int, text: str) -> str:
    mp3 = os.path.join(OUT_DIR, "_s%d.mp3" % i)
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(mp3)
    return mp3


def to_wav(mp3: str, wav: str) -> None:
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", mp3,
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", wav],
        check=True,
    )
    os.remove(mp3)


async def main() -> None:
    if not os.path.exists(FFMPEG):
        sys.exit("找不到 ffmpeg-static：%s" % FFMPEG)
    os.makedirs(OUT_DIR, exist_ok=True)
    for i, text in enumerate(LINES):
        mp3 = await synth(i, text)
        wav = os.path.join(OUT_DIR, "s%d.wav" % i)
        to_wav(mp3, wav)
        size = os.path.getsize(wav)
        print("s%d.wav  %6.1f KB  %s" % (i, size / 1024.0, text[:18]))


if __name__ == "__main__":
    asyncio.run(main())
