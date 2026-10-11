# -*- coding: utf-8 -*-
"""生成小程序 tabBar 图标（线性风格，与底部导航统一配色）。

产出：asr-miniprogram/images/tabbar/<name>.png（常态灰）与 <name>-on.png（选中蓝）
尺寸：81x81（微信 tabBar 推荐尺寸），4 倍超采样后缩小以获得抗锯齿边缘。

用法：python tools/gen_tabbar_icons.py
"""
import os

from PIL import Image, ImageDraw

SIZE = 81
SS = 4  # 超采样倍数
S = SIZE * SS
W = 7 * SS  # 线宽

NORMAL = (154, 160, 166, 255)  # #9aa0a6
ACTIVE = (26, 140, 255, 255)  # #1a8cff
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "asr-miniprogram",
    "images",
    "tabbar",
)


def _p(v):
    """逻辑坐标 → 画布坐标。"""
    return v * SS


def poly(draw, pts, color, width=W, closed=False):
    seq = [_p(v) for pt in pts for v in pt]
    if closed:
        seq += seq[:2]
    draw.line(seq, fill=color, width=width, joint="curve")


def draw_home(d, c):
    """首页：屋顶 + 墙体 + 门。"""
    poly(d, [(7, 38), (40.5, 13), (74, 38)], c)
    poly(d, [(16, 34), (16, 68), (65, 68), (65, 34)], c)
    poly(d, [(33, 68), (33, 50), (48, 50), (48, 68)], c, width=int(W * 0.85))


def draw_book(d, c):
    """学习资源：摊开的书（左右两页 + 书脊）。"""
    poly(d, [(40.5, 27), (12, 20), (12, 58), (40.5, 65)], c)
    poly(d, [(40.5, 27), (69, 20), (69, 58), (40.5, 65)], c)


def draw_mic(d, c):
    """语言采集：麦克风。"""
    d.rounded_rectangle(
        [_p(28.5), _p(12), _p(52.5), _p(46)], radius=_p(12), outline=c, width=W
    )
    d.arc([_p(21), _p(28), _p(60), _p(60)], start=0, end=180, fill=c, width=W)
    poly(d, [(40.5, 60), (40.5, 69)], c)
    poly(d, [(30, 69), (51, 69)], c)


def draw_person(d, c):
    """我的：头像 + 肩部。"""
    d.ellipse([_p(28.5), _p(13), _p(52.5), _p(37)], outline=c, width=W)
    d.arc([_p(15), _p(43), _p(66), _p(86)], start=180, end=360, fill=c, width=W)


ICONS = {
    "home": draw_home,
    "resources": draw_book,
    "record": draw_mic,
    "mine": draw_person,
}


def render(painter, color):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    painter(ImageDraw.Draw(img), color)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, painter in ICONS.items():
        for suffix, color in (("", NORMAL), ("-on", ACTIVE)):
            path = os.path.join(OUT_DIR, f"{name}{suffix}.png")
            render(painter, color).save(path)
            print("wrote", os.path.relpath(path, os.path.dirname(OUT_DIR)).replace("\\", "/"))


if __name__ == "__main__":
    main()
