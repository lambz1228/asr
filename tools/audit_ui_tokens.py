# -*- coding: utf-8 -*-
"""UI 视觉对齐审计：扫描各页面 WXSS，找出偏离 app.wxss 设计令牌的硬编码值。

四条轴：颜色 / 圆角 / 字号 / 阴影。
用法：asr-server/.venv/Scripts/python.exe tools/audit_ui_tokens.py
"""
import collections
import io
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "asr-miniprogram")

COLOR_TOKENS = {
    "--brand": "#1a8cff", "--brand-2": "#58b6ff", "--brand-3": "#0e6fd8",
    "--brand-soft": "#e9f4ff",
    "--green": "#07c160", "--green-2": "#35d07f", "--green-soft": "#e7f8ef",
    "--amber": "#ff9500", "--amber-soft": "#fff5e6",
    "--red": "#f0453a", "--red-soft": "#ffeeec",
    "--violet": "#7c5cff", "--violet-soft": "#f0ecff",
    "--bg": "#eef1f6", "--card": "#ffffff", "--t1": "#12171f", "--t2": "#5a6470",
    "--t3": "#98a1ac", "--t4": "#c3c9d1", "--line": "#edf0f4",
}
RADIUS_TOKENS = {"32rpx": "--r-xl", "24rpx": "--r-lg", "18rpx": "--r-md", "12rpx": "--r-sm"}

# 旧 Vant 风格色板 -> 应对齐到的令牌（人工判定，用于给建议）
LEGACY_MAP = {
    "#1989fa": "--brand", "#2b8cff": "--brand", "#2b7cff": "--brand", "#0f78e0": "--brand-3",
    "#4aa8ff": "--brand-lt", "#3ea3ff": "--brand-2", "#6dc4ff": "--brand-2",
    "#e64340": "--red",
    "#ff976a": "--amber", "#ffb340": "--amber-2", "#ffc061": "--amber-2",
    "#fef3c7": "--amber-ink-soft", "#fff5e6": "--amber-soft",
    "#b45309": "--amber-ink", "#b26a00": "--amber-ink",
    "#1a1a1a": "--t1", "#222": "--t1", "#333": "--t1",
    "#555": "--t2", "#666": "--t2",
    "#888": "--t3", "#999": "--t3", "#9aa0a6": "--t3", "#98a4b2": "--t3",
    "#aaa": "--t3",
    "#bbb": "--t4", "#ccc": "--t4", "#c3c9d1": "--t4",
    "#f5f5f5": "--bg 或 --line", "#f2f2f2": "--line",
}

# 有意保留的字面量：这些是刻意的亮度斜坡 / 一次性装饰色，收敛反而会破坏原效果。
# 写明理由，避免下一轮审计再被当成「漏网」。
INTENTIONAL = {
    "#3ea3ff": "首页/资源页头部三段渐变的中间斜坡（映射会压平渐变）",
    "#6dc4ff": "同上，渐变末端更亮的一档",
    "#fffaf0": "琥珀渐变亮端，与 --amber-soft 组成 135deg 斜坡",
    "#e9f3ff": "登录页背景三段渐变起点",
    "#f4f8fd": "登录页背景三段渐变中段",
    "#eef6ff": "资源页卡片渐变亮端",
    "#ddeafc": "资源页卡片渐变暗端",
    "#a9741f": "公告面板琥珀文字阶梯中档（与 --amber-ink 组成层次）",
    "#d9a44e": "公告面板箭头色，琥珀阶梯最亮档",
    "#b7e4cb": "同意书主按钮禁用态浅绿（一次性状态色）",
}

val2tok = {}
for k, v in COLOR_TOKENS.items():
    val2tok.setdefault(v.lower(), []).append(k)


def target_files():
    out = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in files:
            if f.endswith(".wxss"):
                out.append(os.path.join(root, f).replace("\\", "/"))
    return sorted(out)


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def strip_comments(s):
    return re.sub(r"/\*.*?\*/", "", s, flags=re.S)


def main():
    files = [f for f in target_files() if not f.endswith("app.wxss")]
    per_color = collections.defaultdict(collections.Counter)
    total = collections.Counter()
    per_radius = collections.defaultdict(collections.Counter)
    per_font = collections.defaultdict(collections.Counter)
    per_shadow = collections.defaultdict(collections.Counter)
    font_all = collections.Counter()

    for f in files:
        body = strip_comments(io.open(f, encoding="utf-8").read())
        r = rel(f)
        for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", body):
            h = h.lower()
            per_color[r][h] += 1
            total[h] += 1
        for v in re.findall(r"border-radius:\s*([0-9]+rpx)\b", body):
            per_radius[r][v] += 1
        for v in re.findall(r"font-size:\s*([0-9]+rpx)\b", body):
            per_font[r][v] += 1
            font_all[v] += 1
        for v in re.findall(r"box-shadow:\s*([^;]+);", body):
            per_shadow[r][v.strip()] += 1

    line = "=" * 76
    print(line)
    print("一、颜色：硬编码色值频次（不含 app.wxss）")
    print(line)
    for h, n in total.most_common():
        tok = val2tok.get(h)
        if tok:
            note = "  <= 已等价于 " + " / ".join(tok)
        elif h in INTENTIONAL:
            note = "  <= 有意保留：" + INTENTIONAL[h]
        elif h in LEGACY_MAP:
            note = "  <= 旧色板，建议 " + LEGACY_MAP[h]
        else:
            note = ""
        print("  %-10s %3d 次%s" % (h, n, note))

    grand = sum(total.values())
    exact = sum(n for h, n in total.items() if h in val2tok)
    legacy = sum(n for h, n in total.items()
                 if h not in val2tok and h not in INTENTIONAL and h in LEGACY_MAP)
    keep = sum(n for h, n in total.items() if h not in val2tok and h in INTENTIONAL)
    other = grand - exact - legacy - keep
    print("-" * 76)
    print("合计 %d 处硬编码：等价令牌 %d，旧色板待归并 %d，有意保留 %d，其它待判断 %d"
          % (grand, exact, legacy, keep, other))

    axis(per_radius, "二、圆角（令牌：--r-xl 32rpx / --r-lg 24rpx / --r-md 18rpx / --r-sm 12rpx）",
         RADIUS_TOKENS, line)
    axis(per_font, "三、字号（全仓无字号令牌，取值越离散越不对齐）", {}, line)
    print("-" * 76)
    print("字号取值分布（全仓）:")
    for v, n in sorted(font_all.items(), key=lambda x: int(x[0].replace("rpx", ""))):
        print("    %4srpx  %3d 次" % (v, n))
    print("    合计 %d 处，共 %d 种取值（建议收敛到 5~6 级）" % (sum(font_all.values()), len(font_all)))

    axis(per_shadow, "四、阴影写法（令牌：--sd / --sd-md / --sd-lg）", {}, line)

    print()
    print(line)
    print("五、令牌化完整性：字号 / 圆角是否真的写成 var()")
    print(line)
    print("  提示：裸令牌名（`font-size: --fs-8`）是无效 CSS，字号会静默退回默认值，")
    print("        只看有没有 rpx 字面量是查不出来的。")
    bad = 0
    for f in files:
        body = strip_comments(io.open(f, encoding="utf-8").read())
        rows = []
        for v in re.findall(r"font-size:\s*([^;]+);", body):
            if not re.fullmatch(r"var\(--fs-\d+\)", v.strip()):
                rows.append("font-size: " + v.strip())
        for v in re.findall(r"border-radius:\s*([^;]+);", body):
            s = v.strip()
            parts = s.split()
            ok_multi = bool(parts) and all(
                re.fullmatch(r"0|var\(--r-[a-z]+\)", p) for p in parts)
            if not (ok_multi
                    or re.fullmatch(r"[0-9.]+%(\s+[0-9.]+%)*", s)):
                rows.append("border-radius: " + s)
        if rows:
            bad += len(rows)
            print("  %s" % rel(f))
            for r in rows:
                print("      %s" % r)
    print("-" * 76)
    print("未走令牌的声明共 %d 处%s" % (bad, "（应为 0）" if bad else " ✓"))
    return 0


def axis(per_file, title, token_map, line):
    print()
    print(line)
    print(title)
    print(line)
    for f in sorted(per_file):
        c = per_file[f]
        parts = []
        for v, n in sorted(c.items(), key=lambda x: (-x[1], x[0])):
            tag = ""
            if v in token_map:
                tag = "(=%s)" % token_map[v]
            parts.append("%s x%d%s" % (v, n, tag))
        print("  %-44s %s" % (f, "; ".join(parts)))


if __name__ == "__main__":
    sys.exit(main())
