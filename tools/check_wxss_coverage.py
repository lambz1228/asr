# -*- coding: utf-8 -*-
"""WXSS 覆盖度检查：WXML 里用到的 class 是否都有样式定义（本页 WXSS 或全局 app.wxss）。

用途：重构/合并样式后验证「没有把用到的类删掉」。样式表里多余的类不算错，只报告缺失。

用法：asr-server/.venv/Scripts/python.exe tools/check_wxss_coverage.py
"""
import io
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "asr-miniprogram")


def classes_in_wxml(text):
    """提取 WXML 里实际会挂上去的 class。

    只解析 class / hover-class 属性**内部**的表达式，不碰文本节点里的 {{}}，
    否则 {{fileName || '点击选择文件'}} 这类默认文案会被当成一串类名。

    属性内的三元 class="tab {{mode==='paste'?'on':''}}" 中，`paste` 是比较值、
    `on` 才是类名；`{{a ? 'ok' : 'todo'}}` 的 `ok`/`todo` 都会在运行时成为类名。
    所以：只取 `?` 之后的分支字面量。
    """
    out = set()

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
        cleaned = re.sub(r"\{\{(.*?)\}\}", repl, attr, flags=re.S)
        for c in cleaned.split():
            if c and c not in ("?", ":", "||", "&&", "!", "{{", "}}"):
                out.add(c)
    return out


def selectors_in_wxss(text):
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = set()
    # 去掉声明块，只留选择器部分
    for block in re.findall(r"([^{}]+)\{", body):
        for part in block.split(","):
            part = part.strip()
            if not part or part.startswith("@"):
                continue
            for m in re.findall(r"\.([A-Za-z0-9_-]+)", part):
                out.add(m)
    return out


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
    print("=" * 72)
    print("WXSS 覆盖度：WXML 用到但无样式定义的 class")
    print("=" * 72)
    for d in pages:
        names = [f for f in os.listdir(d) if f.endswith(".wxml")]
        for n in names:
            wxml = io.open(os.path.join(d, n), encoding="utf-8").read()
            used = classes_in_wxml(wxml)
            css_path = os.path.join(d, n[:-5] + ".wxss")
            local = set()
            if os.path.exists(css_path):
                local = selectors_in_wxss(io.open(css_path, encoding="utf-8").read())
            known = local | global_css | {"hover-class", "class"}
            missing = sorted(used - known)
            rel = os.path.relpath(os.path.join(d, n), ROOT).replace("\\", "/")
            status = "ok  " if not missing else "MISS"
            print("  %s %-52s 用到 %2d 个类%s" % (
                status, rel, len(used),
                ("" if not missing else "，缺样式: " + ", ".join(missing)),
            ))
            total_missing += len(missing)

    print("-" * 72)
    print("合计缺失 %d 个 class 定义" % total_missing)
    return 1 if total_missing else 0


if __name__ == "__main__":
    sys.exit(main())
