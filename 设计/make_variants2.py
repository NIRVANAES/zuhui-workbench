#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""라일락 · 图标方案 第二批 —— 这次直接用 IU 的实际符号。

已查证（namu.wiki / thewiki.kr 两处一致）：
  · 유애나（官方粉丝名）的官方 logo = 「心形与音符合体」，IU 本人设计
  · 官方应援棒 I-KE Ver.3，应援色 네온 옐로우（霓虹黄）
  · 专辑《LILAC》= 丁香花

  python make_variants2.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "图标方案2"
SYS = Path("C:/Windows/Fonts")
FONTS = Path("E:/WorkBuddy/downloads/fonts")

S, K = 1024, 4
N = S * K
U = N / 1024.0
random.seed(20210325)

LILAC_HI = (176, 150, 236)
LILAC_LO = (92, 63, 168)
NIGHT_HI = (86, 62, 148)
NIGHT_LO = (38, 24, 74)
NEON = (228, 255, 63)
WHITE = (255, 255, 255)
PALE = (226, 214, 250)
PALE2 = (198, 180, 240)
DEEP = (58, 36, 110)


# ---------------------------------------------------------------- 基础工具
def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def squircle(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def gradient(size, top, bottom):
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


def plate(top=LILAC_HI, bottom=LILAC_LO, glow=(0.74, 0.80), glow_peak=34):
    img = gradient(N, top, bottom).convert("RGBA")
    t = Image.new("L", (1, N), 0)
    tp = t.load()
    for y in range(N):
        k = y / (N * 0.55)
        tp[0, y] = 0 if k >= 1 else round(34 * (1 - k) ** 1.7)
    img = Image.composite(Image.new("RGBA", (N, N), WHITE), img, t.resize((N, N), Image.NEAREST))
    if glow_peak:
        img = Image.composite(Image.new("RGBA", (N, N), NEON + (255,)), img,
                              radial(N, glow[0] * N, glow[1] * N, 620 * U, glow_peak, 2.3))
    img.putalpha(squircle(N, N * 0.2237))
    return img


def ellipse_poly(cx, cy, rx, ry, deg=0.0, n=72):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + (rx * math.cos(2 * math.pi * i / n)) * ca - (ry * math.sin(2 * math.pi * i / n)) * sa,
             cy + (rx * math.cos(2 * math.pi * i / n)) * sa + (ry * math.sin(2 * math.pi * i / n)) * ca)
            for i in range(n)]


def heart_poly(cx, cy, half_w, n=200):
    """经典心形参数曲线，缩放到指定半宽并自动居中。"""
    raw = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        raw.append((x, -y))                      # 屏幕 y 向下
    xs = [p[0] for p in raw]; ys = [p[1] for p in raw]
    s = (2 * half_w) / (max(xs) - min(xs))
    ox = (max(xs) + min(xs)) / 2
    oy = (max(ys) + min(ys)) / 2
    return [(cx + (x - ox) * s, cy + (y - oy) * s) for x, y in raw]


def note_shapes(x0, y0, w, h, rot=-10.0):
    """单枚八分音符：符头 + 符干 + 符尾。返回多边形列表。"""
    def P(u, v):
        return (x0 + u * w, y0 + v * h)

    head = ellipse_poly(*P(0.26, 0.76), w * 0.235, h * 0.170, rot)
    stem = [P(0.455, 0.72), P(0.545, 0.72), P(0.545, 0.06), P(0.455, 0.06)]
    flag = [P(0.545, 0.05), P(0.80, 0.24), P(0.76, 0.44), P(0.60, 0.33), P(0.545, 0.28)]
    return [head, stem, flag]


def alpha_of(layer):
    return layer.split()[3]


def glow_under(img, mask, color, blur, strength=170, dx=0, dy=0):
    g = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    g.paste(color + (strength,), (round(dx), round(dy)), mask)
    return Image.alpha_composite(img, g.filter(ImageFilter.GaussianBlur(blur)))


# ---------------------------------------------------------------- 六个方案
def v1_heart_note():
    """心 · 音符（负空间）—— 直接把 유애나 官方标志画出来。"""
    img = plate((176, 150, 236), (92, 63, 168), glow_peak=0)
    cx = cy = N / 2
    heart = heart_poly(cx, cy, 372 * U)

    m = Image.new("L", (N, N), 0)
    ImageDraw.Draw(m).polygon(heart, fill=255)
    # 把音符从心里挖掉
    cut = Image.new("L", (N, N), 0)
    cd = ImageDraw.Draw(cut)
    for shp in note_shapes(cx - 232 * U, cy - 268 * U, 470 * U, 512 * U):
        cd.polygon(shp, fill=255)
    m = Image.composite(Image.new("L", (N, N), 0), m, cut)

    img = glow_under(img, m, NEON, 62 * U, 150)
    img = glow_under(img, m, NEON, 22 * U, 120)
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    layer.paste(NEON + (255,), (0, 0), m)
    img = Image.alpha_composite(img, layer)
    return img


def v2_glowing_heart():
    """心 · 发光 —— 暗场里的一颗心，像演唱会举起的灯。"""
    img = plate(NIGHT_HI, NIGHT_LO, glow=(0.5, 0.62), glow_peak=26)
    cx, cy = N / 2, N / 2
    heart = heart_poly(cx, cy, 300 * U)

    m = Image.new("L", (N, N), 0)
    ImageDraw.Draw(m).polygon(heart, fill=255)

    img = glow_under(img, m, NEON, 104 * U, 170)
    img = glow_under(img, m, NEON, 36 * U, 200)

    # 心内部：上白下霓虹的渐变，让它像在发光
    inner = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    body = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    bd.polygon(heart, fill=(255, 255, 255, 255))
    col = Image.new("RGB", (1, N))
    cp = col.load()
    top_y, bot_y = min(p[1] for p in heart), max(p[1] for p in heart)
    span = max(1.0, bot_y - top_y)
    for y in range(N):
        t = min(1.0, max(0.0, (y - top_y) / span))
        cp[0, y] = lerp((247, 255, 168), NEON, min(1.0, t * 2.2))
    grad = col.resize((N, N), Image.NEAREST).convert("RGBA")
    body = Image.composite(grad, body, alpha_of(body))
    img = Image.alpha_composite(img, body)
    return img


def v3_heart_pages():
    """心 · 两页 —— 心里摊开两页，把粉丝符号和这个 app 的用途接上。"""
    img = plate((176, 150, 236), (92, 63, 168), glow_peak=0)
    cx = cy = N / 2
    heart = heart_poly(cx, cy, 380 * U)

    ring = Image.new("L", (N, N), 0)
    rd = ImageDraw.Draw(ring)
    rd.polygon(heart, fill=255)
    inner = Image.new("L", (N, N), 0)
    ImageDraw.Draw(inner).polygon(heart_poly(cx, cy, 380 * U * 0.84), fill=255)
    ring = Image.composite(Image.new("L", (N, N), 0), ring, inner)

    img = glow_under(img, ring, NEON, 40 * U, 110)
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    lay.paste(NEON + (255,), (0, 0), ring)
    img = Image.alpha_composite(img, lay)

    d = ImageDraw.Draw(img)
    pw, ph, gap = 204 * U, 262 * U, 22 * U
    for sign in (-1, 1):
        x0 = cx + (gap / 2 if sign > 0 else -gap / 2 - pw)
        y0 = cy - ph / 2 + 42 * U
        d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=26 * U, fill=WHITE + (255,))
        ly = y0 + 40 * U
        for k, wf in enumerate((1.0, 0.92, 1.0, 0.6)):
            d.rounded_rectangle([x0 + 26 * U, ly, x0 + 26 * U + (pw - 52 * U) * wf, ly + 15 * U],
                                radius=8 * U, fill=PALE2 + (255,))
            ly += 30 * U
    return img


def v4_heart_lilac():
    """心 · 丁香 —— 一颗霓虹心，右下角别一朵小丁香。"""
    img = plate((180, 156, 238), (94, 64, 172), glow_peak=0)
    cx, cy = N / 2 - 26 * U, N / 2 - 26 * U
    heart = heart_poly(cx, cy, 322 * U)
    hm = Image.new("L", (N, N), 0)
    ImageDraw.Draw(hm).polygon(heart, fill=255)

    img = glow_under(img, hm, NEON, 66 * U, 150)
    img = glow_under(img, hm, NEON, 24 * U, 120)
    hl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    hl.paste(NEON + (255,), (0, 0), hm)
    img = Image.alpha_composite(img, hl)

    # 右下角一朵小丁香，压住心的边缘
    fx, fy = N * 0.735, N * 0.745
    fl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fl)
    R, D = 46 * U, 42 * U
    for deg in (-90, 0, 90, 180):
        a = math.radians(deg)
        px, py = fx + math.cos(a) * D, fy + math.sin(a) * D
        fd.ellipse([px - R, py - R, px + R, py + R], fill=WHITE + (255,))
    fd.ellipse([fx - 30 * U, fy - 30 * U, fx + 30 * U, fy + 30 * U], fill=(128, 98, 198, 235))
    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sh.paste((46, 26, 92, 110), (round(7 * U), round(10 * U)), alpha_of(fl))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(20 * U)))
    return Image.alpha_composite(img, fl)


def v5_lightstick():
    """应援棒 —— 一支举起来的手灯，灯头里一颗心。"""
    img = plate(NIGHT_HI, NIGHT_LO, glow=(0.5, 0.34), glow_peak=30)
    cx = N / 2
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)

    # 握柄
    hw, hh = 92 * U, 400 * U
    hx, hy = cx - hw / 2, N * 0.50
    ld.rounded_rectangle([hx, hy, hx + hw, hy + hh], radius=hw / 2, fill=(238, 233, 250, 245))
    ld.rounded_rectangle([hx + hw * 0.30, hy + 26 * U, hx + hw * 0.70, hy + hh - 26 * U],
                         radius=hw * 0.20, fill=(214, 203, 240, 220))
    # 灯头
    head_r = 168 * U
    hcy = hy - head_r * 0.86
    ld.ellipse([cx - head_r, hcy - head_r, cx + head_r, hcy + head_r], fill=(250, 248, 255, 250))

    img = glow_under(img, alpha_of(lay), (200, 190, 245), 46 * U, 130)
    img = Image.alpha_composite(img, lay)

    # 灯头里的心：霓虹黄
    heart = heart_poly(cx, hcy + 12 * U, head_r * 0.62)
    hm = Image.new("L", (N, N), 0)
    ImageDraw.Draw(hm).polygon(heart, fill=255)
    img = glow_under(img, hm, NEON, 40 * U, 150)
    hl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    hl.paste(NEON + (255,), (0, 0), hm)
    img = Image.alpha_composite(img, hl)
    return img


def v6_lilac_heart():
    """丁香心 —— 用一朵朵小丁香排成一颗心。"""
    img = plate((184, 160, 240), (98, 68, 176), glow_peak=0)
    cx = cy = N / 2
    heart = heart_poly(cx, cy, 330 * U)

    # 沿心形轮廓均匀取点
    step = max(1, len(heart) // 44)
    pts = heart[::step]
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)

    for i, (px, py) in enumerate(pts):
        neon = (i % 7 == 3)
        col = NEON if neon else (WHITE if i % 3 else PALE)
        r = 30 * U
        d = 34 * U
        for deg in (-90, 0, 90, 180):
            a = math.radians(deg)
            x, y = px + math.cos(a) * d, py + math.sin(a) * d
            ld.ellipse([x - r, y - r, x + r, y + r], fill=col + (255,))
        ld.ellipse([px - r * 0.62, py - r * 0.62, px + r * 0.62, py + r * 0.62],
                   fill=(120, 92, 190, 190))

    img = glow_under(img, alpha_of(lay), (255, 255, 255), 26 * U, 90)
    return Image.alpha_composite(img, lay)


OPTIONS = [
    ("方案 1 · 心 · 音符", "유애나 官方标志：心形与音符合体（IU 亲自设计）", v1_heart_note),
    ("方案 2 · 心 · 发光", "暗场里的一颗心，像演唱会举起的灯", v2_glowing_heart),
    ("方案 3 · 心 · 两页", "心里摊开两页，符号与用途合一", v3_heart_pages),
    ("方案 4 · 心 · 丁香", "一颗霓虹心，右下角别一朵小丁香", v4_heart_lilac),
    ("方案 5 · 应援棒", "一支手灯，灯头里一颗霓虹黄的心", v5_lightstick),
    ("方案 6 · 丁香心", "用一朵朵小丁香排成一颗心", v6_lilac_heart),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    imgs = []
    for name, desc, fn in OPTIONS:
        im = fn()
        png = OUT / (name.split(" · ")[0] + ".png")
        im.resize((S, S), Image.LANCZOS).save(png, optimize=True)
        imgs.append((name, desc, im))
        print("生成", png.name)

    f_cjk = ImageFont.truetype(str(SYS / "Deng.ttf"), 26)
    f_cjk_b = ImageFont.truetype(str(SYS / "Dengb.ttf"), 32)
    f_kr = ImageFont.truetype(str(SYS / "malgun.ttf"), 34)

    BIG, SMALLS = 210, (64, 40, 24)
    GAP, PAD = 30, 34
    cellw = BIG + 20 + sum(SMALLS) + 12 * len(SMALLS)
    cellh = BIG + 16 + 46
    cols, rows = 3, 2
    W = PAD * 2 + cols * cellw + (cols - 1) * GAP
    H = PAD * 2 + 66 + rows * cellh + (rows - 1) * GAP

    sheet = Image.new("RGB", (W, H), (247, 245, 252))
    sd = ImageDraw.Draw(sheet)
    sd.text((PAD, PAD - 6), "라일락", font=f_kr, fill=(42, 35, 64))
    sd.text((PAD + 118, PAD - 4), "· 图标方案（第二批 · IU 符号）", font=f_cjk_b, fill=(42, 35, 64))
    sd.text((PAD + 560, PAD + 6), "心 · 音符 / 灯海 / 应援棒 —— 全部来自 IU 的实际符号",
            font=f_cjk, fill=(120, 108, 150))

    for i, (name, desc, im) in enumerate(imgs):
        c, r = i % cols, i // cols
        x = PAD + c * (cellw + GAP)
        y = PAD + 66 + r * (cellh + GAP)
        sd.rounded_rectangle([x - 12, y - 12, x + cellw + 12, y + cellh + 8],
                             radius=18, fill=(255, 255, 255), outline=(226, 220, 244))
        sheet.paste(im.resize((BIG, BIG), Image.LANCZOS).convert("RGB"), (x, y))
        sx = x + BIG + 20
        for s in SMALLS:
            sheet.paste(im.resize((s, s), Image.LANCZOS).convert("RGB"), (sx, y + BIG - s))
            sx += s + 12
        sd.text((x, y + BIG + 14), name, font=f_cjk_b, fill=(58, 46, 96))
        sd.text((x, y + BIG + 52), desc, font=f_cjk, fill=(132, 120, 162))

    out = HERE / "方案对照2.png"
    sheet.save(out, optimize=True)
    print("对照图 ->", out, sheet.size)


if __name__ == "__main__":
    main()
