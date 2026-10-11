# -*- coding: utf-8 -*-
"""
头像后处理：裁掉生成图右下角的半透明水印，导出 512×512 的成品头像。

为什么裁而不是修：水印固定在右下角（实测 bbox ≈ x 904-1012 / y 964-1013），
本批图的主体都居中偏上，正方形裁到 (62,56)-(962,956) 既能完整避开，
又保持水平居中、垂直仅偏移 6px。

用法：
    python tools/prepare_avatars.py
输入：assets/avatars/*.png（ImageGen 原始输出，含水印）
输出：assets/avatars/<语义名>.png（512×512，无水印）+ _sheet.png（总览）
      原始图移到 assets/avatars/_raw/
"""
import glob
import os
import shutil
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AVATARS = os.path.join(ROOT, "assets", "avatars")
RAW_DIR = os.path.join(AVATARS, "_raw")

# 裁切框（避开右下角水印，边长 900）
CROP = (62, 56, 962, 956)
OUT_SIZE = 512

# 原始文件名关键字 -> 语义化文件名
RULES = [
    ("App_icon_for_a_voice", "brand-microphone"),
    ("concentric_glow", "brand-soundwave"),
    ("symmetric_aud", "brand-waveform"),
]
# 人物头像按生成时间顺序对应：采集员(女) / 采集员(男) / 审核员(女)
PORTRAIT_NAMES = ["user-collector-female", "user-collector-male", "user-reviewer-female"]


def main() -> None:
    srcs = [p for p in sorted(glob.glob(os.path.join(AVATARS, "*.png")))
            if not os.path.basename(p).startswith("_")
            and "_sheet" not in os.path.basename(p)]
    if not srcs:
        sys.exit("没有找到待处理的生成图：%s" % AVATARS)

    mapping = {}
    portraits = []
    for p in srcs:
        base = os.path.basename(p)
        matched = False
        for key, name in RULES:
            if key in base:
                mapping[name] = p
                matched = True
                break
        if not matched:
            portraits.append(p)

    portraits.sort()  # 文件名含 ISO 时间戳，字典序即生成顺序
    for i, p in enumerate(portraits):
        if i < len(PORTRAIT_NAMES):
            mapping[PORTRAIT_NAMES[i]] = p

    done = []
    for name, src in mapping.items():
        im = Image.open(src).convert("RGB")
        im = im.crop(CROP).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
        dst = os.path.join(AVATARS, name + ".png")
        im.save(dst)
        done.append((name, dst))
        print("  %-26s <- %s" % (name + ".png", os.path.basename(src)))

    # 六宫格总览（2 行 3 列）
    cols, rows, gap = 3, 2, 16
    sheet = Image.new("RGB", (cols * OUT_SIZE + gap * (cols + 1),
                              rows * OUT_SIZE + gap * (rows + 1)), (12, 18, 30))
    for i, (name, path) in enumerate(done):
        im = Image.open(path)
        x = gap + (i % cols) * (OUT_SIZE + gap)
        y = gap + (i // cols) * (OUT_SIZE + gap)
        sheet.paste(im, (x, y))
    sheet_path = os.path.join(AVATARS, "_sheet.png")
    sheet.save(sheet_path)
    print("总览：%s" % sheet_path)

    # 原始图归档
    os.makedirs(RAW_DIR, exist_ok=True)
    for p in srcs:
        shutil.move(p, os.path.join(RAW_DIR, os.path.basename(p)))
    print("原始图已归档到 _raw/（共 %d 张）" % len(srcs))


if __name__ == "__main__":
    main()
