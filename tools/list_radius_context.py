# -*- coding: utf-8 -*-
"""列出 WXSS 中 >=16rpx 的 border-radius 及其所属选择器，用于人工判定「胶囊 vs 卡片」。

用法：asr-server/.venv/Scripts/python.exe tools/list_radius_context.py
"""
import io
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "asr-miniprogram")


def main():
    files = []
    for root, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in fs:
            if f.endswith(".wxss"):
                files.append(os.path.join(root, f))
    files.sort()

    for path in files:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        body = re.sub(r"/\*.*?\*/", "", io.open(path, encoding="utf-8").read(), flags=re.S)
        rows = []
        for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", body):
            sel = " ".join(block.group(1).split())
            decl = block.group(2)
            for m in re.finditer(r"border-radius:\s*([0-9]+)rpx", decl):
                v = int(m.group(1))
                if v >= 16:
                    rows.append((sel, v))
        if rows:
            print("== %s" % rel)
            for sel, v in rows:
                pill = ""
                if re.search(r"tab|chip|badge|pill|tag|dot|flag", sel):
                    pill = "   <- 疑似胶囊"
                print("    %-42s %3drpx%s" % (sel, v, pill))
    return 0


if __name__ == "__main__":
    sys.exit(main())
