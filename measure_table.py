#!/usr/bin/env python3
"""分析表格行的列间距：列与列之间必须有可见空隙，否则 Word 里文字会粘连。"""
import re
import sys
from collections import defaultdict

path = sys.argv[1]
html = open(path, encoding="utf-8").read()

# 按页、按行聚合
pages = html.split("<page")
for pno, p in enumerate(pages[1:], 1):
    words = []
    for m in re.finditer(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', p):
        words.append((float(m.group(1)), float(m.group(2)), float(m.group(3)),
                      float(m.group(4)), m.group(5)))
    rows = defaultdict(list)
    for w in words:
        rows[round(w[1], 1)].append(w)

    for y in sorted(rows):
        ws = sorted(rows[y])
        if len(ws) < 3:
            continue
        line = "".join(x[4] for x in ws)
        if "方法" not in line and "Baseline" not in line:
            continue
        gaps = []
        for a, b in zip(ws, ws[1:]):
            gaps.append(round(b[0] - a[2], 1))
        print(f"页{pno} y={y}: {line[:40]}")
        print(f"   词间 x 间隙: {gaps}")
