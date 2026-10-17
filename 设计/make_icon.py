#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""팔레트 —— 「组会工作台」应用图标

淡紫渐变底 + 一枚白色调色盘，拇指孔是真的挖穿的（不是画个透明圆就完事），
颜料点用 IU 官方应援色霓虹黄与专辑《LILAC》的淡紫，霓黄两点带光。

在 4 倍分辨率下绘制，最后一次性降采样。

  python make_icon.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
OUT = HERE.parent          # 与工作台放在同一目录，便于直接做 favicon

S, K = 1024, 4
N = S * K
U = N / 1024.0

LILAC_HI = (176, 150, 236)
LILAC_LO = (92, 63, 168)
NEON = (228, 255, 63)
WHITE = (255, 255, 255)
PALE = (226, 214, 250)
MID = (150, 118, 214)
FAINT = (238, 231, 253)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def squircle_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def vertical_gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    px = g.load()
    for y in range(size):
        px[0, y] = lerp(top, bottom, y / max(1, size - 1))
    return g.resize((size, size), Image.NEAREST)


def radial(size, cx, cy, r_max, peak, power):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    for i in range(90, 0, -1):
        r = r_max * i / 90
        a = round(peak * (1 - i / 90) ** power)
        if a > 0:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    return m


def ellipse_poly(cx, cy, rx, ry, deg=0.0, n=96):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + (rx * math.cos(2 * math.pi * i / n)) * ca - (ry * math.sin(2 * math.pi * i / n)) * sa,
             cy + (rx * math.cos(2 * math.pi * i / n)) * sa + (ry * math.sin(2 * math.pi * i / n)) * ca)
            for i in range(n)]


def main():
    # ---------------- 底：淡紫渐变 + 顶部受光 + 右下霓虹回光 ----------------
    img = vertical_gradient(N, LILAC_HI, LILAC_LO).convert("RGBA")
    top = Image.new("L", (1, N), 0)
    tp = top.load()
    for y in range(N):
        k = y / (N * 0.55)
        tp[0, y] = 0 if k >= 1 else round(34 * (1 - k) ** 1.7)
    img = Image.composite(Image.new("RGBA", (N, N), WHITE), img, top.resize((N, N), Image.NEAREST))
    img = Image.composite(Image.new("RGBA", (N, N), NEON + (255,)), img,
                          radial(N, 0.78 * N, 0.80 * N, 620 * U, 30, 2.3))
    img.putalpha(squircle_mask(N, N * 0.2237))

    # ---------------- 调色盘 ----------------
    cx, cy = N / 2, N / 2 + 22 * U
    rx, ry = 396 * U, 316 * U

    # 盘面蒙版：整片椭圆 减去 拇指孔
    board = Image.new("L", (N, N), 0)
    ImageDraw.Draw(board).polygon(ellipse_poly(cx, cy, rx, ry), fill=255)
    hole = Image.new("L", (N, N), 0)
    ImageDraw.Draw(hole).ellipse([cx - 268 * U, cy + 74 * U, cx - 108 * U, cy + 234 * U], fill=255)
    board = Image.composite(Image.new("L", (N, N), 0), board, hole)

    # 投影
    def glow(mask, color, blur, a):
        g = Image.new("RGBA", (N, N), (0, 0, 0, 0))
        g.paste(color + (a,), (round(9 * U), round(13 * U)), mask)
        return g.filter(ImageFilter.GaussianBlur(blur))

    img = Image.alpha_composite(img, glow(board, (54, 30, 104), 34 * U, 130))

    # 盘面本体：上浅下深，给一点体积
    col = Image.new("RGB", (1, N))
    cp = col.load()
    for y in range(N):
        t = min(1.0, max(0.0, (y - (cy - ry)) / max(1.0, 2 * ry)))
        cp[0, y] = lerp((253, 252, 255), (231, 224, 250), t)
    body = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    body.paste(col.resize((N, N), Image.NEAREST).convert("RGBA"), (0, 0), board)
    img = Image.alpha_composite(img, body)

    # ---------------- 颜料点 ----------------
    dots = [
        (-152, NEON, 58, True),
        (-104, WHITE, 50, False),
        (-56, PALE, 50, False),
        (-8, MID, 50, False),
        (40, FAINT, 50, False),
        (88, NEON, 54, True),
    ]
    for ang, color, r, lit in dots:
        a = math.radians(ang)
        px = cx + math.cos(a) * rx * 0.60
        py = cy + math.sin(a) * ry * 0.60
        rr = r * U
        m = Image.new("L", (N, N), 0)
        ImageDraw.Draw(m).ellipse([px - rr, py - rr, px + rr, py + rr], fill=255)
        if lit:
            g = Image.new("RGBA", (N, N), (0, 0, 0, 0))
            g.paste(NEON + (150,), (0, 0), m)
            img = Image.alpha_composite(img, g.filter(ImageFilter.GaussianBlur(30 * U)))
        # 颜料点自身的一点凹陷感：上沿一道更亮的边
        lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
        lay.paste(color + (255,), (0, 0), m)
        img = Image.alpha_composite(img, lay)

    # ---------------- 输出 ----------------
    icon = img.resize((S, S), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / "icon.png"
    icon.save(png, optimize=True)
    print("icon ->", png, "(%dx%d, %.0f KB)" % (icon.width, icon.height, png.stat().st_size / 1024))

    ico = OUT / "icon.ico"
    icon.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon ->", ico, "(%.0f KB)" % (ico.stat().st_size / 1024))


if __name__ == "__main__":
    main()
