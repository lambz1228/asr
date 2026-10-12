# -*- coding: utf-8 -*-
"""WXSS 覆盖度检查（双向）。

正向：WXML 里用到的 class 是否都有样式定义（本页 WXSS 或全局 app.wxss）。
反向：本页 WXSS 定义的 class 是否还能被引用到——WXML 改了、样式没跟着删，
      会留下永不生效的死样式（login 页曾残留 .subtitle/.dev-tip/.footer）。

反向检查的两类「看起来死、其实活着」必须放过，否则全是误报：
  1. 裸插值拼类名：`class="status {{item.status}}"` —— item.status 的取值
     在数据里，静态不可知。识别方法是看复合选择器：若 `.status.approved`
     的第一段 `status` 在本页 WXML 里带了动态尾巴，则 `approved` 视为可能被拼上。
  2. 模板拼接：record.wxml 的 `class="{{slideCls}}"`，值由 TS 拼成 `s-${dir}1`，
     静态化后登记在 DYNAMIC_CLASSES。

注意**不要**把「TS 里出现过的任意字符串字面量」当作已用信号——home.ts 的
statusText 映射表里就有 claimed/pending/rejected，会把真死样式一并放过。

用法：asr-server/.venv/Scripts/python.exe tools/check_wxss_coverage.py
"""
import io
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "asr-miniprogram")

# 由模板拼接产生的类名，静态化后登记在此（改了 record.ts 的 slideCls 记得同步）
DYNAMIC_CLASSES = {"s-r1", "s-r2", "s-l1", "s-l2"}


def analyze_wxml(text):
    """返回 (实际会挂上去的 class 集合, 带动态尾巴的 base class 集合)。

    只解析 class / hover-class 属性**内部**的表达式，不碰文本节点里的 {{}}，
    否则 {{fileName || '点击选择文件'}} 这类默认文案会被当成一串类名。

    属性内的 `{{a ? 'ok' : 'todo'}}` 取 `?` 之后的字面量（比较值不是类名）；
    `{{item.status}}` 这种裸插值取不到值，只能把承载它的静态 token 记进
    dynamic_bases，交由复合选择器规则兜底。
    """
    classes = set()
    dynamic_bases = set()

    def repl(m):
        expr = m.group(1)
        tail = expr.split("?", 1)[1] if "?" in expr else ""
        vals = []
        for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", tail):
            vals.append(a or b)
        return " " + " ".join(vals) + " "

    attrs = re.findall(r'class="([^"]*)"', text) + re.findall(r"class='([^']*)'", text)
    attrs += re.findall(r'hover-class="([^"]*)"', text)
    for attr in attrs:
        has_dyn = "{{" in attr
        cleaned = re.sub(r"\{\{(.*?)\}\}", repl, attr, flags=re.S)
        for c in cleaned.split():
            if not c or c in ("?", ":", "||", "&&", "!", "{{", "}}"):
                continue
            classes.add(c)
            if has_dyn:
                # 这个 token 后面可能跟着数据里来的类名，如 status + 'approved'
                dynamic_bases.add(c)
    return classes, dynamic_bases


def selectors_in_wxss(text):
    """本页样式表里出现的所有 class 名（含复合选择器里的修饰类）。"""
    out = set()
    for chain in compound_chains(text):
        out |= set(chain)
    return out


def compound_chains(text):
    """把每个选择器片段拆成 class 链，如 `.status.approved` -> ['status','approved']。

    保留顺序，供「base 带动态尾巴 -> 修饰类视为已用」的规则使用。
    """
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    chains = []
    for block in re.findall(r"([^{}]+)\{", body):
        for part in block.split(","):
            part = part.strip()
            if not part or part.startswith("@"):
                continue
            chain = re.findall(r"\.([A-Za-z0-9_-]+)", part)
            if chain:
                chains.append(chain)
    return chains


def main():
    global_css = ""
    gpath = os.path.join(ROOT, "app.wxss")
    if os.path.exists(gpath):
        global_css = selectors_in_wxss(io.open(gpath, encoding="utf-8").read())

    pages = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        if "wxml" in [f.rsplit(".", 1)[-1] for f in files]:
            pages.append(root)
    pages.sort()

    total_missing = 0
    total_dead = 0
    print("=" * 72)
    print("WXSS 覆盖度：WXML 用到但无样式定义的 class")
    print("=" * 72)
    for d in pages:
        for n in sorted(f for f in os.listdir(d) if f.endswith(".wxml")):
            wxml = io.open(os.path.join(d, n), encoding="utf-8").read()
            used, _ = analyze_wxml(wxml)
            css_path = os.path.join(d, n[:-5] + ".wxss")
            local = set()
            if os.path.exists(css_path):
                local = selectors_in_wxss(io.open(css_path, encoding="utf-8").read())
            known = local | global_css | {"hover-class", "class"}
            missing = sorted(used - known)
            rel = os.path.relpath(os.path.join(d, n), ROOT).replace("\\", "/")
            print("  %s %-52s 用到 %2d 个类%s" % (
                "ok  " if not missing else "MISS", rel, len(used),
                ("" if not missing else "，缺样式: " + ", ".join(missing)),
            ))
            total_missing += len(missing)

    print("")
    print("=" * 72)
    print("WXSS 死样式：本页样式表定义了、但页面引用不到的 class")
    print("=" * 72)
    for d in pages:
        for n in sorted(f for f in os.listdir(d) if f.endswith(".wxml")):
            css_path = os.path.join(d, n[:-5] + ".wxss")
            if not os.path.exists(css_path):
                continue
            text = io.open(css_path, encoding="utf-8").read()
            local = selectors_in_wxss(text)
            wxml = io.open(os.path.join(d, n), encoding="utf-8").read()
            used, dynamic_bases = analyze_wxml(wxml)
            used |= DYNAMIC_CLASSES
            # 规则 1：复合选择器 .base.mod 的 base 带动态尾巴时，mod 可能被数据拼上
            for chain in compound_chains(text):
                if len(chain) >= 2 and chain[0] in dynamic_bases:
                    used |= set(chain)
            dead = sorted(local - used - global_css)
            rel = os.path.relpath(css_path, ROOT).replace("\\", "/")
            if dead:
                print("  DEAD %-52s 死样式: %s" % (rel, ", ".join("." + x for x in dead)))
            total_dead += len(dead)

    print("-" * 72)
    print("合计缺失 %d 个 class 定义；死样式 %d 个" % (total_missing, total_dead))
    return 1 if (total_missing or total_dead) else 0


if __name__ == "__main__":
    sys.exit(main())
