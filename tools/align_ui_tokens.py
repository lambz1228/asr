# -*- coding: utf-8 -*-
"""UI 视觉对齐 codemod：把各页 WXSS 的硬编码值收敛到 app.wxss 设计令牌。

四条轴：颜色 / 字号 / 圆角 / 阴影。app.wxss 本身是令牌定义处，不参与替换。

默认 dry-run（只打印将发生的替换次数），加 --apply 才写盘；重复执行幂等。

用法：
  asr-server/.venv/Scripts/python.exe tools/align_ui_tokens.py            # 预览
  asr-server/.venv/Scripts/python.exe tools/align_ui_tokens.py --apply    # 落地
"""
import collections
import io
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "asr-miniprogram")

# --------------------------------------------------------------------------- 颜色
COLOR_MAP = {
    # —— 与令牌完全等值（零视觉变化）——
    "#07c160": "var(--green)",
    "#1a8cff": "var(--brand)",
    "#58b6ff": "var(--brand-2)",
    "#0e6fd8": "var(--brand-3)",
    "#35d07f": "var(--green-2)",
    "#ff9500": "var(--amber)",
    "#f0453a": "var(--red)",
    "#7c5cff": "var(--violet)",
    "#eef1f6": "var(--bg)",
    "#edf0f4": "var(--line)",
    "#12171f": "var(--t1)",
    "#5a6470": "var(--t2)",
    "#98a1ac": "var(--t3)",
    "#c3c9d1": "var(--t4)",
    # —— 品牌蓝的近似漂移，收敛到 --brand / --brand-2 / --brand-3 ——
    "#1989fa": "var(--brand)",   # 旧 Vant 主蓝
    "#2b8cff": "var(--brand)",
    "#2b7cff": "var(--brand)",
    "#4a90ff": "var(--brand)",
    "#0f78e0": "var(--brand-3)",
    "#4aa8ff": "var(--brand-lt)",
    "#0f78e0": "var(--brand-3)",
    "#e07f00": "var(--amber-3)",
    "#d8352b": "var(--red-3)",
    # 注意：首页/资源页头部的三段渐变 `#1a8cff 0%, #3ea3ff 52%, #6dc4ff 100%`
    # 中间两档是有意拉长的亮度斜坡，映射到同一令牌会把渐变压平（尾段反而变暗），
    # 故 #3ea3ff / #6dc4ff 保留字面量，不进映射表。
    "#7db4ff": "var(--brand-2)",
    "#5a86ff": "var(--brand-2)",
    # —— 绿 / 红 / 紫 / 橙 的近似漂移 ——
    "#20d47a": "var(--green-2)",
    "#e64340": "var(--red)",
    "#ff8579": "var(--red-2)",
    "#ff7a72": "var(--red-2)",
    "#a58bff": "var(--violet-2)",
    "#7c6cff": "var(--violet)",
    "#ff976a": "var(--amber)",
    "#ffb340": "var(--amber-2)",
    "#ffc061": "var(--amber-2)",
    # —— 旧色板的琥珀标签（#b45309 系文字 / #fef3c7 系底）——
    "#b45309": "var(--amber-ink)",
    "#b26a00": "var(--amber-ink)",
    "#8a5300": "var(--amber-ink)",
    "#a05a00": "var(--amber-ink)",
    "#8a3b39": "var(--amber-ink)",
    "#fef3c7": "var(--amber-ink-soft)",
    "#ffe2b0": "var(--amber-line)",
    "#ffe0b2": "var(--amber-line)",
    "#fff2d8": "var(--amber-soft)",
    "#f0c2c0": "var(--red-line)",
    "#f7c9c5": "var(--red-line)",
    # —— 灰阶收敛到 --t1..--t4 ——
    "#1a1a1a": "var(--t1)",
    "#222": "var(--t1)",
    "#333": "var(--t1)",
    "#555": "var(--t2)",
    "#666": "var(--t2)",
    "#888": "var(--t3)",
    "#999": "var(--t3)",
    "#aaa": "var(--t3)",
    "#9aa0a6": "var(--t3)",   # tabBar 未选中灰
    "#98a4b2": "var(--t3)",
    "#6b7480": "var(--t2)",
    "#bbb": "var(--t4)",
    "#ccc": "var(--t4)",
    "#b9c3cf": "var(--t4)",
    "#d7dde5": "var(--t4)",
    # —— 浅蓝面 / 蓝底上的文字 ——
    "#eaf3ff": "var(--brand-soft)",
    "#e2eefc": "var(--brand-soft)",
    "#ff5a4e": "var(--red)",
    # —— 极浅面板色收敛到 --surface-2 ——
    "#f0f2f6": "var(--surface-2)",
    "#f2f4f8": "var(--surface-2)",
    "#f4f6fa": "var(--surface-2)",
    "#f6f8fb": "var(--surface-2)",
    "#f7f9fc": "var(--surface-2)",
    # —— 其它 ——
    "#576b95": "var(--brand)",   # 旧微信链接蓝 → 品牌蓝
}
# 白色按属性区分语义：背景用 --card，前景（文字/描边）用 --on-brand
WHITE_BG = "var(--card)"
WHITE_FG = "var(--on-brand)"
FG_PROPS = ("color", "fill", "stroke", "outline",
            "border", "border-color", "border-top", "border-top-color",
            "border-bottom", "border-bottom-color", "border-left", "border-left-color",
            "border-right", "border-right-color")

# --------------------------------------------------------------------------- 字号
FONT_MAP = {
    "20": "--fs-1", "21": "--fs-1",
    "22": "--fs-2", "23": "--fs-2",
    "24": "--fs-3", "25": "--fs-3",
    "26": "--fs-4", "27": "--fs-4",
    "28": "--fs-5", "29": "--fs-5",
    "30": "--fs-6", "31": "--fs-6",
    "32": "--fs-7",
    "36": "--fs-8", "38": "--fs-8",
    "40": "--fs-9",
    "44": "--fs-10",
    "48": "--fs-11",
    "56": "--fs-12",
    "68": "--fs-13",
    "76": "--fs-14",
    "96": "--fs-15",
}

# --------------------------------------------------------------------------- 圆角
RADIUS_LADDER = [(8, "--r-xs"), (12, "--r-sm"), (18, "--r-md"), (24, "--r-lg"), (32, "--r-xl")]
# 同语义元素统一形状：胶囊、图标底、logo（仅当半径 >= 16rpx 时生效）
RADIUS_BY_SELECTOR = {
    "tab": "--r-pill", "tab-chip": "--r-pill", "chip": "--r-pill",
    "badge": "--r-pill", "role": "--r-pill", "role-tag": "--r-pill",
    "role-chip": "--r-pill", "toolbar": "--r-pill",
    "entry-ico": "--r-lg", "feat-ico": "--r-lg", "item-ico": "--r-lg",
    "rule-ico": "--r-lg", "hero-emoji": "--r-lg",
    "logo": "--r-xl",
}

# --------------------------------------------------------------------------- 阴影
# 只收敛「6rpx/8rpx 偏移」的图标光晕与通用卡片阴影；
# 偏移 >= 12rpx 的主视觉光晕与 tabBar 向上投影保留原样（属设计取舍，不无脑塌平）。
SHADOW_MAP = {
    "0 4rpx 14rpx rgba(20, 33, 56, 0.05)": "var(--sd)",
    "0 6rpx 16rpx rgba(26, 140, 255, 0.24)": "var(--sd-brand)",
    "0 6rpx 16rpx rgba(74, 144, 255, 0.24)": "var(--sd-brand)",
    "0 6rpx 16rpx rgba(7, 193, 96, 0.24)": "var(--sd-green)",
    "0 6rpx 16rpx rgba(255, 149, 0, 0.26)": "var(--sd-amber)",
    "0 8rpx 18rpx rgba(26, 140, 255, 0.24)": "var(--sd-brand)",
    "0 8rpx 18rpx rgba(26, 140, 255, 0.26)": "var(--sd-brand)",
    "0 8rpx 18rpx rgba(26, 140, 255, 0.28)": "var(--sd-brand)",
    "0 8rpx 20rpx rgba(26, 140, 255, 0.26)": "var(--sd-brand)",
    "0 8rpx 20rpx rgba(26, 140, 255, 0.28)": "var(--sd-brand)",
    "0 8rpx 20rpx rgba(26, 140, 255, 0.3)": "var(--sd-brand)",
    "0 8rpx 18rpx rgba(7, 193, 96, 0.22)": "var(--sd-green)",
    "0 8rpx 18rpx rgba(7, 193, 96, 0.24)": "var(--sd-green)",
    "0 8rpx 20rpx rgba(7, 193, 96, 0.28)": "var(--sd-green)",
    "0 8rpx 18rpx rgba(124, 92, 255, 0.22)": "var(--sd-violet)",
    "0 8rpx 18rpx rgba(124, 92, 255, 0.24)": "var(--sd-violet)",
    "0 8rpx 18rpx rgba(255, 149, 0, 0.22)": "var(--sd-amber)",
    "0 8rpx 22rpx rgba(20, 40, 90, 0.2)": "var(--sd-md)",
}

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
DECL_RE = re.compile(r"(?P<prop>[a-zA-Z-]+)(?P<sep>\s*:\s*)(?P<val>[^;{}]+?)(?P<end>\s*;)")
BLOCK_RE = re.compile(r"(?P<sel>[^{}]+)\{(?P<body>[^{}]*)\}", re.S)


def last_class(sel):
    cls = re.findall(r"\.([A-Za-z0-9_-]+)", sel)
    return cls[-1] if cls else ""


def replace_colors(val, prop):
    def sub(m):
        h = m.group(0).lower()
        if h in ("#fff", "#ffffff"):
            return WHITE_FG if prop in FG_PROPS else WHITE_BG
        return COLOR_MAP.get(h, m.group(0))
    return HEX_RE.sub(sub, val)


def fix_decl(m, sel, stats):
    prop = m.group("prop").strip().lower()
    val = m.group("val")
    new = val

    if prop == "font-size":
        mm = re.fullmatch(r"\s*([0-9]+)rpx\s*", val)
        if mm and mm.group(1) in FONT_MAP:
            new = "var(%s)" % FONT_MAP[mm.group(1)]
            stats["字号"] += 1

    elif prop == "border-radius":
        # 支持单值与多值（如 `0 0 40rpx 40rpx`）；0 与百分比原样保留
        parts = val.split()
        if parts and all(re.fullmatch(r"[0-9]+rpx|0", p) for p in parts):
            lc = last_class(sel)
            out_parts = []
            touched = False
            for p in parts:
                if p == "0":
                    out_parts.append("0")
                    continue
                v = int(p[:-3])
                tok = RADIUS_BY_SELECTOR.get(lc) if v >= 16 else None
                if not tok:
                    tok = min(RADIUS_LADDER, key=lambda x: abs(x[0] - v))[1]
                out_parts.append("var(%s)" % tok)
                touched = True
            if touched:
                new = " ".join(out_parts)
                stats["圆角"] += 1

    elif prop == "box-shadow":
        key = " ".join(val.split())
        if key in SHADOW_MAP:
            new = SHADOW_MAP[key]
            stats["阴影"] += 1

    else:
        nv = replace_colors(val, prop)
        if nv != val:
            stats["颜色"] += 1
            new = nv

    return m.group("prop") + m.group("sep") + new + m.group("end")


def process(text, stats):
    """先给注释打上哨兵，避免注释里的色值/写法被误替换，处理完再还原。"""
    comments = []

    def mask(m):
        comments.append(m.group(0))
        return "/*__C%d__*/" % (len(comments) - 1)

    masked = re.sub(r"/\*.*?\*/", mask, text, flags=re.S)

    def on_block(bm):
        sel = bm.group("sel")
        body = DECL_RE.sub(lambda m: fix_decl(m, sel, stats), bm.group("body"))
        return sel + "{" + body + "}"

    out = BLOCK_RE.sub(on_block, masked)
    return re.sub(r"/\*__C(\d+)__\*/", lambda m: comments[int(m.group(1))], out)


def main():
    apply = "--apply" in sys.argv
    files = []
    for root, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in fs:
            if f.endswith(".wxss"):
                files.append(os.path.join(root, f))
    files.sort()

    total = collections.Counter()
    changed = []
    print("=" * 70)
    print("UI 视觉对齐：" + ("落地写入" if apply else "预览（dry-run，未写盘）"))
    print("=" * 70)
    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        if rel == "app.wxss":
            print("  %-48s 跳过（令牌定义处）" % rel)
            continue
        src = io.open(path, encoding="utf-8").read()
        stats = collections.Counter()
        out = process(src, stats)
        n = sum(stats.values())
        total.update(stats)
        if n:
            changed.append(rel)
        if n:
            detail = "  ".join("%s×%d" % (k, stats[k]) for k in ("颜色", "字号", "圆角", "阴影") if stats[k])
            print("  %-48s %3d 处  %s" % (rel, n, detail))
        else:
            print("  %-48s   0 处" % rel)
        if apply and out != src:
            io.open(path, "w", encoding="utf-8", newline="\n").write(out)

    print("-" * 70)
    print("合计 %d 处：颜色 %d / 字号 %d / 圆角 %d / 阴影 %d，涉及 %d 个文件"
          % (sum(total.values()), total["颜色"], total["字号"], total["圆角"], total["阴影"], len(changed)))
    if not apply:
        print("（未写盘；确认无误后加 --apply 落地）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
