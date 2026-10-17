#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""라일락 · 图标方案对照 —— 一次生成 6 个方向，拼成对照图供挑选。

  python make_variants.py

产出：
  方案对照.png          3×2 网格，每个方案含大图 + 64/40/24px 小尺寸
  方案1.png … 方案6.png  各 1024×1024 单图
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "图标方案"
SYS = Path("C:/Windows/Fonts")

S, K = 1024, 4
N = S * K
U = N / 1024.0

LILAC_HI = (176, 150, 236)
LILAC_LO = (92, 63, 168)
LILAC_MID = (128, 98, 200)
NEON = (228, 255, 63)
WHITE = (255, 255, 255)
PALE = (226, 214, 250)
PALE2 = (198, 180, 240)
DEEP = (74, 48, 138)


# ------------------------------------------------------------------ 基础工具
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


def radial_alpha(size, cx, cy, r_max, peak, power):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    steps = 80
    for i in range(steps, 0, -1):
        r = r_max * i / steps
        a = round(peak * (1 - i / steps) ** power)
        if a > 0:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    return m


def base_plate(glow_at=(0.72, 0.78)):
    """所有方案共用的底：淡紫渐变 + 顶部受光 + 右下霓虹回光 + squircle 圆角。"""
    img = gradient(N, LILAC_HI, LILAC_LO).convert("RGBA")
    top = Image.new("L", (1, N), 0)
    tp = top.load()
    for y in range(N):
        t = y / (N * 0.55)
        tp[0, y] = 0 if t >= 1 else round(36 * (1 - t) ** 1.7)
    img = Image.composite(Image.new("RGBA", (N, N), WHITE), img, top.resize((N, N), Image.NEAREST))
    g = radial_alpha(N, glow_at[0] * N, glow_at[1] * N, 620 * U, 34, 2.3)
    img = Image.composite(Image.new("RGBA", (N, N), NEON + (255,)), img, g)
    img.putalpha(squircle(N, N * 0.2237))
    return img


def petal(cx, cy, rx, ry, deg, n=72):
    """以 (cx,cy) 为心、旋转 deg 度的椭圆多边形（PIL 不能直接画旋转椭圆）。"""
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def rrect(d, x0, y0, x1, y1, r, fill):
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)


def shadow(layer, blur):
    return layer.filter(ImageFilter.GaussianBlur(blur))


def flatten(img, size=S):
    return img.resize((size, size), Image.LANCZOS).convert("RGB")


# ------------------------------------------------------------------ 六个方案
def opt1_floret():
    """花冠：真正的花瓣形状，三白一霓虹，浅紫花心。"""
    img = base_plate((0.74, 0.80))
    cx = cy = N / 2

    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for deg in (-90, 0, 90, 180):
        a = math.radians(deg)
        px, py = cx + math.cos(a) * 214 * U, cy + math.sin(a) * 214 * U
        sd.polygon(petal(px + 8 * U, py + 10 * U, 66 * U, 204 * U, deg), fill=(56, 32, 106, 80))
    img = Image.alpha_composite(img, shadow(sh, 26 * U))

    d = ImageDraw.Draw(img)
    for deg, col in ((-90, WHITE), (0, WHITE), (90, WHITE), (180, NEON)):
        a = math.radians(deg)
        px, py = cx + math.cos(a) * 214 * U, cy + math.sin(a) * 214 * U
        d.polygon(petal(px, py, 66 * U, 204 * U, deg), fill=col + (255,))
    d.ellipse([cx - 34 * U, cy - 34 * U, cx + 34 * U, cy + 34 * U], fill=PALE + (255,))
    return img


def _pages(img, pw, ph, gap, tilt, lines=True, mark=None):
    """对开两页的公共画法。"""
    cx = cy = N / 2
    left = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    right = Image.new("RGBA", (N, N), (0, 0, 0, 0))

    def draw_page(layer, x0, y0, flipped):
        d = ImageDraw.Draw(layer)
        rrect(d, x0, y0, x0 + pw, y0 + ph, 48 * U, WHITE + (255,))
        if not lines:
            return
        pad = 46 * U
        lx = x0 + pad
        lw = pw - pad * 2
        ly = y0 + 74 * U
        if mark == "chart":
            for i, w in enumerate((1.0, 1.0, 1.0, 0.62)):
                rrect(d, lx, ly, lx + lw * w, ly + 26 * U, 13 * U, PALE2 + (255,))
                ly += 52 * U
            rrect(d, lx, ly + 8 * U, lx + lw, ly + 8 * U + 150 * U, 18 * U, PALE + (255,))
        else:
            for i, w in enumerate((1.0, 1.0, 0.88, 1.0, 0.55)):
                rrect(d, lx, ly, lx + lw * w, ly + 26 * U, 13 * U, PALE2 + (255,))
                ly += 52 * U

    draw_page(left, cx - gap / 2 - pw, cy - ph / 2, False)
    draw_page(right, cx + gap / 2, cy - ph / 2, True)

    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sh.alpha_composite(left)
    sh.alpha_composite(right)
    sh = sh.filter(ImageFilter.GaussianBlur(0))
    # 投影：复制一份整体下移后模糊
    proj = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    proj.paste((56, 32, 106, 92), (round(10 * U), round(14 * U)), sh.split()[3])
    img = Image.alpha_composite(img, shadow(proj, 26 * U))

    if tilt:
        left = left.rotate(tilt, resample=Image.BICUBIC, center=(cx - gap / 2 - pw / 2, cy))
        right = right.rotate(-tilt, resample=Image.BICUBIC, center=(cx + gap / 2 + pw / 2, cy))
    img = Image.alpha_composite(img, left)
    img = Image.alpha_composite(img, right)
    return img


def opt2_book():
    """对开两页：左右微微外翻，左页文字、右页图表。"""
    img = base_plate((0.78, 0.24))
    return _pages(img, 340 * U, 430 * U, 34 * U, 4.0, lines=True, mark="chart")


def opt3_pages_floret():
    """两页 + 花：书页为主体，右下角盖一枚小丁香。"""
    img = base_plate((0.80, 0.82))
    img = _pages(img, 272 * U, 344 * U, 28 * U, 3.0, lines=True, mark=None)
    cx, cy = N * 0.755, N * 0.775
    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for deg in (-90, 0, 90, 180):
        a = math.radians(deg)
        px, py = cx + math.cos(a) * 78 * U, cy + math.sin(a) * 78 * U
        sd.polygon(petal(px + 5 * U, py + 7 * U, 44 * U, 74 * U, deg), fill=(56, 32, 106, 90))
    img = Image.alpha_composite(img, shadow(sh, 18 * U))
    d = ImageDraw.Draw(img)
    for deg, col in ((-90, WHITE), (0, WHITE), (90, WHITE), (180, NEON)):
        a = math.radians(deg)
        px, py = cx + math.cos(a) * 78 * U, cy + math.sin(a) * 78 * U
        d.polygon(petal(px, py, 44 * U, 74 * U, deg), fill=col + (255,))
    d.ellipse([cx - 22 * U, cy - 22 * U, cx + 22 * U, cy + 22 * U], fill=DEEP + (255,))
    return img


def opt4_blossom():
    """大花：一朵占满画布，霓虹黄花心。"""
    img = base_plate((0.76, 0.78))
    cx = cy = N / 2
    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for deg in (-90, 0, 90, 180):
        a = math.radians(deg)
        px, py = cx + math.cos(a) * 214 * U, cy + math.sin(a) * 214 * U
        sd.polygon(petal(px + 9 * U, py + 12 * U, 104 * U, 214 * U, deg), fill=(56, 32, 106, 80))
    img = Image.alpha_composite(img, shadow(sh, 28 * U))
    d = ImageDraw.Draw(img)
    for deg in (-90, 0, 90, 180):
        a = math.radians(deg)
        px, py = cx + math.cos(a) * 214 * U, cy + math.sin(a) * 214 * U
        d.polygon(petal(px, py, 104 * U, 214 * U, deg), fill=WHITE + (255,))
    d.ellipse([cx - 66 * U, cy - 66 * U, cx + 66 * U, cy + 66 * U], fill=NEON + (255,))
    return img


def opt5_open_book():
    """展开的书：透视，中间一道书脊阴影。"""
    img = base_plate((0.80, 0.22))
    cx = N / 2
    top_i, bot_i = N * 0.305, N * 0.735
    top_o, bot_o = N * 0.365, N * 0.685
    half = N * 0.315

    def page(sign):
        xi = cx + sign * N * 0.012
        xo = cx + sign * half
        return (xi, top_i), (xi, bot_i), (xo, bot_o), (xo, top_o)

    def at(q, u, v):
        (it, ib, ob, ot) = q
        x = (1 - u) * ((1 - v) * it[0] + v * ib[0]) + u * ((1 - v) * ot[0] + v * ob[0])
        y = (1 - u) * ((1 - v) * it[1] + v * ib[1]) + u * ((1 - v) * ot[1] + v * ob[1])
        return (x, y)

    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for sign in (-1, 1):
        q = page(sign)
        sd.polygon([q[0], q[1], q[2], q[3]], fill=(56, 32, 106, 95))
    proj = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    proj.paste((56, 32, 106, 100), (round(10 * U), round(16 * U)), sh.split()[3])
    img = Image.alpha_composite(img, shadow(proj, 28 * U))

    d = ImageDraw.Draw(img)
    for sign in (-1, 1):
        q = page(sign)
        d.polygon([q[0], q[1], q[2], q[3]], fill=WHITE + (255,))
        # 页上内容：沿透视方向铺几条线
        for k, (v0, u1, thick) in enumerate((
                (0.16, 0.86, 0.030), (0.30, 0.94, 0.030),
                (0.44, 0.72, 0.030), (0.58, 0.90, 0.030), (0.72, 0.55, 0.030))):
            a = at(q, 0.10, v0)
            b = at(q, u1, v0)
            c = at(q, u1, v0 + thick)
            e = at(q, 0.10, v0 + thick)
            d.polygon([a, b, c, e], fill=PALE2 + (255,))
    # 书脊
    d.polygon([(cx - N * 0.014, top_i), (cx + N * 0.014, top_i),
               (cx + N * 0.014, bot_i), (cx - N * 0.014, bot_i)], fill=PALE + (255,))
    # 霓虹书签：让这枚图标带上 라일락 的那一点黄
    q = page(1)
    a1, b1 = at(q, 0.13, -0.05), at(q, 0.30, -0.05)
    c1, e1 = at(q, 0.30, 0.17), at(q, 0.13, 0.17)
    mid = at(q, 0.215, 0.26)
    d.polygon([a1, b1, c1, mid, e1], fill=NEON + (255,))
    return img


def opt6_cards():
    """双页交叠：两张圆角卡片错开叠放，一实一透。"""
    img = base_plate((0.80, 0.78))
    cx = cy = N / 2
    cw, ch = 380 * U, 470 * U
    back = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    bd = ImageDraw.Draw(back)
    rrect(bd, cx - cw / 2 - 62 * U, cy - ch / 2 + 34 * U,
          cx + cw / 2 - 62 * U, cy + ch / 2 + 34 * U, 54 * U, (255, 255, 255, 118))
    back = back.rotate(-9, resample=Image.BICUBIC, center=(cx, cy))
    img = Image.alpha_composite(img, back)

    front = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    fd = ImageDraw.Draw(front)
    x0, y0 = cx - cw / 2 + 52 * U, cy - ch / 2 - 18 * U
    rrect(fd, x0, y0, x0 + cw, y0 + ch, 54 * U, WHITE + (255,))
    pad = 52 * U
    ly = y0 + 84 * U
    for w in (1.0, 1.0, 0.86, 1.0, 0.6):
        rrect(fd, x0 + pad, ly, x0 + pad + (cw - pad * 2) * w, ly + 28 * U, 14 * U, PALE2 + (255,))
        ly += 56 * U
    rrect(fd, x0 + pad, ly + 6 * U, x0 + pad + (cw - pad * 2) * 0.42,
          ly + 6 * U + 34 * U, 17 * U, NEON + (255,))
    front = front.rotate(5, resample=Image.BICUBIC, center=(cx, cy))

    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sh.paste((56, 32, 106, 95), (round(12 * U), round(18 * U)), front.split()[3])
    img = Image.alpha_composite(img, shadow(sh, 28 * U))
    return Image.alpha_composite(img, front)


OPTIONS = [
    ("方案 1 · 花冠", "丁香十字花冠，三白瓣一霓虹瓣", opt1_floret),
    ("方案 2 · 对开两页", "左页文字 / 右页图表，微微外翻", opt2_book),
    ("方案 3 · 两页加花", "书页为主体，右下角盖一枚小丁香", opt3_pages_floret),
    ("方案 4 · 大花", "一朵占满画布，霓虹黄花心", opt4_blossom),
    ("方案 5 · 展开的书", "透视展开，中间一道书脊", opt5_open_book),
    ("方案 6 · 双页交叠", "两张卡片错开叠放，一实一透", opt6_cards),
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

    # ---------------- 对照图 ----------------
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
    sd.text((PAD + 118, PAD - 4), "· 图标方案对照", font=f_cjk_b, fill=(42, 35, 64))
    sd.text((PAD + 430, PAD + 6), "每个方案都给了 210 / 64 / 40 / 24 px 四个尺寸",
            font=f_cjk, fill=(120, 108, 150))

    for i, (name, desc, im) in enumerate(imgs):
        c, r = i % cols, i // cols
        x = PAD + c * (cellw + GAP)
        y = PAD + 66 + r * (cellh + GAP)
        sd.rounded_rectangle([x - 12, y - 12, x + cellw + 12, y + cellh + 8],
                             radius=18, fill=(255, 255, 255), outline=(226, 220, 244))
        sheet.paste(flatten(im, BIG), (x, y))
        sx = x + BIG + 20
        for s in SMALLS:
            sheet.paste(flatten(im, s), (sx, y + BIG - s))
            sx += s + 12
        sd.text((x, y + BIG + 14), name, font=f_cjk_b, fill=(58, 46, 96))
        sd.text((x, y + BIG + 52), desc, font=f_cjk, fill=(132, 120, 162))

    out = HERE / "方案对照.png"
    sheet.save(out, optimize=True)
    print("对照图 ->", out, sheet.size)


if __name__ == "__main__":
    main()
