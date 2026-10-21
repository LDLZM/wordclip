#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成扩展图标：宣纸圆角底 + 描金字母 W + 朱砂印章角标，纯标准库（手写 PNG）。

设计取舍（小尺寸看得清才是好图标）：
  - 16/32 像素下不做细笔画，W 用"折线加粗"而不是字体轮廓，避免糊成一团；
  - 印章只在 >=32 像素时画，16 像素上省略（否则会压住 W）；
  - 所有坐标按画布比例算，四档图标视觉一致。
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "icons"

INK = (42, 37, 32)
GOLD = (168, 121, 31)
RED = (168, 52, 31)
PAPER_A = (250, 246, 236)
PAPER_B = (240, 231, 213)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def seg_dist(x, y, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy or 1e-9
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


# W 的五个折点（0..1 坐标）；笔画粗细随尺寸缩放
W_PTS = [(0.16, 0.28), (0.31, 0.72), (0.50, 0.52), (0.69, 0.72), (0.84, 0.28)]


def render(size):
    px = [[None] * size for _ in range(size)]
    # 笔画粗细按字号比例给：32/48/128 用 0.078，16 像素要更粗才立得住
    thick = 0.100 if size <= 16 else (0.080 if size <= 32 else 0.072)
    stamp = size >= 32
    # 圆角半径：小图用 2.5 像素的观感
    r = max(1.6, size * 0.16)

    for yy in range(size):
        for xx in range(size):
            x = (xx + 0.5) / size
            y = (yy + 0.5) / size
            col = lerp(PAPER_A, PAPER_B, (x * 0.6 + y * 0.4))
            # 圆角：四角超出圆弧的像素透明（PNG 走 RGB，用纸色边缘近似无法透明，
            # 所以这里用"深墨描边"表达边界，而不是透明）
            cx = min(max(x, r / size), 1 - r / size)
            cy = min(max(y, r / size), 1 - r / size)
            outside = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 > r / size
            if outside:
                col = INK
            elif x < 0.055 or x > 0.945 or y < 0.055 or y > 0.945:
                col = INK
            else:
                # 描金 W
                d = min(seg_dist(x, y, *W_PTS[i], *W_PTS[i + 1])
                        for i in range(len(W_PTS) - 1))
                if d <= thick:
                    col = GOLD
                # 朱砂印章角标（只在 >=32px 画，避免压住 W）
                if stamp and size >= 48:
                    x0, y0, x1, y1 = 0.70, 0.66, 0.93, 0.90
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        edge = (x < x0 + 0.030 or x > x1 - 0.030 or
                                y < y0 + 0.030 or y > y1 - 0.030)
                        col = RED if edge else lerp(RED, PAPER_A, 0.80)
            px[yy][xx] = col
    return px


def write_png(path, px):
    size = len(px)
    raw = bytearray()
    for row in px:
        raw.append(0)
        for r, g, b in row:
            raw += bytes((r, g, b))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    path.write_bytes(png)
    return len(png)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for s in (16, 32, 48, 128):
        n = write_png(OUT / f"icon{s}.png", render(s))
        print(f"icon{s}.png  {n} bytes")
