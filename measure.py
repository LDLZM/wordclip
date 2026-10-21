#!/usr/bin/env python3
"""从 pdftotext -bbox 的输出测量版面：字号、行距、缩进、是否溢出页边距。"""
import re
import sys
from collections import defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prev/c3.x.html"
html = open(path, encoding="utf-8").read()

words = []
for m in re.finditer(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
        html):
    x0, y0, x1, y1, txt = float(m.group(1)), float(m.group(2)), \
        float(m.group(3)), float(m.group(4)), m.group(5)
    words.append((x0, y0, x1, y1, txt))

# 按行聚合
rows = defaultdict(list)
for w in words:
    rows[round(w[1], 1)].append(w)

print(f"总词数: {len(words)}  文本行数: {len(rows)}")
print()

# 字号直方图（高度）
heights = defaultdict(int)
for w in words:
    h = round(w[3] - w[1], 1)
    heights[h] += 1
print("字号分布（字框高度 pt → 词数）:")
for h, c in sorted(heights.items()):
    print(f"  {h:5.1f}pt  x{c}")

print()
# 左边界分布：正文应有大量相同 xMin（缩进后），续行应更靠左
lefts = defaultdict(int)
for w in words:
    lefts[round(w[0])] += 1
print("最常用的左边界（pt → 词数）:")
for x, c in sorted(lefts.items(), key=lambda kv: -kv[1])[:8]:
    print(f"  x={x:4d}pt  x{c}")

print()
# 行距：相邻且左边界接近的行
ys = sorted(rows)
gaps = []
for a, b in zip(ys, ys[1:]):
    g = b - a
    if 8 < g < 40:
        gaps.append(round(g, 1))
if gaps:
    avg = sum(gaps) / len(gaps)
    print(f"平均行间距: {avg:.1f}pt  (最小 {min(gaps)}, 最大 {max(gaps)})")

print()
# 页面右边界检查：A4 595pt，右边距 90pt → 内容右界应 <= 505
over = [(w[2] - 505) for w in words if w[2] > 507]
print("超出右边距的词数:", len(over))

print()
print("前 30 行的首个词与 xMin:")
for y in ys[:30]:
    ws = sorted(rows[y])
    print(f"  y={y:6.1f} x={ws[0][0]:6.1f} h={ws[0][3]-ws[0][1]:4.1f}  {ws[0][4][:40]}")
