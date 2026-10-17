#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""라일락 · 图标方案 第三批 —— 从 IU 的歌曲 / 专辑意象里取符号。

  · 밤편지（夜信）：夜里写的信 —— 也暗合「读论文」
  · 팔레트（Palette）：调色盘 —— 也暗合「做幻灯片」
  · 음표（音符）：UAENA 标志里的音符，单独放大
  · 꽃다발（花束）：一束丁香，霓虹黄缎带扎起
  · 하트 + 별（心星）：心上一道星芒
  · 책 + 하트（书与心）：摊开的书 + 霓虹心书签

  python make_variants3.py
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from make_variants2 import (
    N, U, plate, heart_poly, ellipse_poly, glow_under, alpha_of, radial,
    NEON, WHITE, PALE, PALE2, LILAC_HI, LILAC_LO, NIGHT_HI, NIGHT_LO, note_shapes,
)

OUT = HERE / "图标方案3"
SYS = Path("C:/Windows/Fonts")
random.seed(20210420)


def sparkle(cx, cy, r, inner=0.30, rot=-90.0):
    """四角星芒（8 个顶点交替长短）。"""
    pts = []
    for i in range(8):
        t = math.radians(rot) + math.pi * 2 * i / 8
        rr = r if i % 2 == 0 else r * inner
        pts.append((cx + math.cos(t) * rr, cy + math.sin(t) * rr))
    return pts


def v1_night_letter():
    """밤편지：夜色底一颗星，一封待拆的信，火漆是霓虹黄的心。"""
    img = plate(NIGHT_HI, NIGHT_LO, glow_peak=0)
    cx, cy = N / 2, N / 2

    # 星点
    st = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sd = ImageDraw.Draw(st)
    for _ in range(14):
        x = N * (0.08 + random.random() * 0.84)
        y = N * (0.06 + random.random() * 0.40)
        r = (7 + 9 * random.random()) * U
        sd.polygon(sparkle(x, y, r * 3.4), fill=(255, 255, 255, 200))
    img = Image.alpha_composite(img, st.filter(ImageFilter.GaussianBlur(2)))

    # 信封
    w, h = 620 * U, 400 * U
    x0, y0 = cx - w / 2, cy - h / 2 + 40 * U
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    ld.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=44 * U, fill=(250, 249, 255, 252))
    # 封口折线
    ld.polygon([(x0, y0), (cx, y0 + 172 * U), (x0 + w, y0)], fill=PALE + (255,))
    img = glow_under(img, alpha_of(lay), (120, 96, 190), 42 * U, 120)
    img = Image.alpha_composite(img, lay)

    # 火漆：一颗霓虹心
    hm = Image.new("L", (N, N), 0)
    ImageDraw.Draw(hm).polygon(heart_poly(cx, y0 + 160 * U, 96 * U), fill=255)
    img = glow_under(img, hm, NEON, 40 * U, 150)
    hl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    hl.paste(NEON + (255,), (0, 0), hm)
    return Image.alpha_composite(img, hl)


def v2_palette():
    """팔레트：调色盘，颜料点是淡紫、白与霓虹黄。"""
    img = plate(LILAC_HI, LILAC_LO, glow_peak=0)
    cx, cy = N / 2, N / 2 + 20 * U

    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    rx, ry = 400 * U, 320 * U
    ld.polygon(ellipse_poly(cx, cy, rx, ry), fill=(252, 251, 255, 252))
    # 拇指孔
    ld.ellipse([cx - 250 * U, cy + 92 * U, cx - 90 * U, cy + 252 * U], fill=(0, 0, 0, 0))
    img = glow_under(img, alpha_of(lay), (120, 96, 190), 42 * U, 120)
    img = Image.alpha_composite(img, lay)

    # 颜料点：沿上缘排开
    d = ImageDraw.Draw(img)
    cols = [NEON, WHITE, PALE, (150, 118, 214), (236, 228, 252), NEON]
    for i, col in enumerate(cols):
        a = math.radians(-160 + i * 26)
        px = cx + math.cos(a) * rx * 0.62
        py = cy + math.sin(a) * ry * 0.62
        r = (52 if col == NEON else 46) * U
        g = Image.new("L", (N, N), 0)
        ImageDraw.Draw(g).ellipse([px - r, py - r, px + r, py + r], fill=255)
        if col == NEON:
            img = glow_under(img, g, NEON, 34 * U, 150)
        gl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
        gl.paste(col + (255,), (0, 0), g)
        img = Image.alpha_composite(img, gl)
    return img


def v3_note():
    """음표：UAENA 标志里的那一枚音符，单独放大。"""
    img = plate(LILAC_HI, LILAC_LO, glow_peak=0)
    m = Image.new("L", (N, N), 0)
    md = ImageDraw.Draw(m)
    for shp in note_shapes(N * 0.235, N * 0.215, 560 * U, 620 * U):
        md.polygon(shp, fill=255)
    img = glow_under(img, m, NEON, 66 * U, 155)
    img = glow_under(img, m, NEON, 24 * U, 120)
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    lay.paste(NEON + (255,), (0, 0), m)
    return Image.alpha_composite(img, lay)


def v4_bouquet():
    """꽃다발：一束丁香，霓虹黄缎带扎在下部。"""
    img = plate(LILAC_HI, LILAC_LO, glow_peak=0)
    cx, cy = N / 2, N / 2 - 30 * U

    fl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fl)
    pts = []
    for _ in range(30):
        v = random.random() ** 0.72
        y = cy + (v - 0.62) * 620 * U
        x = cx + (random.random() - 0.5) * (300 + 560 * v) * U
        pts.append((x, y, v))

    for x, y, v in pts:
        R = (44 + 30 * (1 - v)) * U
        D = R * 0.88
        neon = random.random() < 0.14
        col = NEON if neon else (WHITE if random.random() < 0.55 else PALE)
        for deg in (-90, 0, 90, 180):
            a = math.radians(deg)
            px, py = x + math.cos(a) * D, y + math.sin(a) * D
            fd.ellipse([px - R, py - R, px + R, py + R], fill=col + (255,))
        fd.ellipse([x - R * 0.44, y - R * 0.44, x + R * 0.44, y + R * 0.44], fill=(122, 94, 192, 210))
    img = glow_under(img, alpha_of(fl), (255, 255, 255), 26 * U, 95)
    img = Image.alpha_composite(img, fl)

    # 缎带
    ty = cy + 250 * U
    rib = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rib)
    rd.rounded_rectangle([cx - 132 * U, ty, cx + 132 * U, ty + 64 * U], radius=32 * U, fill=NEON + (255,))
    for s in (-1, 1):
        rd.polygon([(cx + s * 108 * U, ty + 26 * U),
                    (cx + s * 232 * U, ty - 56 * U),
                    (cx + s * 236 * U, ty + 26 * U),
                    (cx + s * 118 * U, ty + 78 * U)], fill=NEON + (255,))
    gm = Image.new("L", (N, N), 0)
    gm.paste(alpha_of(rib), (0, 0))
    img = glow_under(img, gm, NEON, 34 * U, 140)
    return Image.alpha_composite(img, rib)


def v5_heart_star():
    """하트 + 별：一颗心，右上角一道霓虹星芒。"""
    img = plate(LILAC_HI, LILAC_LO, glow_peak=0)
    cx, cy = N / 2 - 24 * U, N / 2 + 10 * U
    heart = heart_poly(cx, cy, 340 * U)

    hm = Image.new("L", (N, N), 0)
    ImageDraw.Draw(hm).polygon(heart, fill=255)
    img = glow_under(img, hm, NEON, 62 * U, 150)
    img = glow_under(img, hm, NEON, 22 * U, 120)
    hl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    hl.paste(NEON + (255,), (0, 0), hm)
    img = Image.alpha_composite(img, hl)

    # 星芒压在心右上角
    sx, sy = cx + 250 * U, cy - 232 * U
    sm = Image.new("L", (N, N), 0)
    ImageDraw.Draw(sm).polygon(sparkle(sx, sy, 168 * U, 0.28), fill=255)
    img = glow_under(img, sm, (255, 255, 255), 36 * U, 140)
    sl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sl.paste(WHITE + (255,), (0, 0), sm)
    return Image.alpha_composite(img, sl)


def v6_book_heart():
    """책 + 하트：摊开的书，一枚霓虹心书签垂下来。"""
    img = plate(LILAC_HI, LILAC_LO, glow_peak=0)
    cx = N / 2
    top_i, bot_i = N * 0.315, N * 0.725
    top_o, bot_o = N * 0.372, N * 0.678
    half = N * 0.318

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
    img = Image.alpha_composite(img, proj.filter(ImageFilter.GaussianBlur(28 * U)))

    d = ImageDraw.Draw(img)
    for sign in (-1, 1):
        q = page(sign)
        d.polygon([q[0], q[1], q[2], q[3]], fill=WHITE + (255,))
        for v0, u1 in ((0.18, 0.86), (0.32, 0.94), (0.46, 0.72), (0.60, 0.90), (0.74, 0.55)):
            a, b = at(q, 0.10, v0), at(q, u1, v0)
            c, e = at(q, u1, v0 + 0.030), at(q, 0.10, v0 + 0.030)
            d.polygon([a, b, c, e], fill=PALE2 + (255,))
    d.polygon([(cx - N * 0.014, top_i), (cx + N * 0.014, top_i),
               (cx + N * 0.014, bot_i), (cx - N * 0.014, bot_i)], fill=PALE + (255,))

    # 霓虹心书签
    q = page(1)
    hx = at(q, 0.44, -0.02)[0]
    hy = at(q, 0.44, -0.02)[1]
    hm = Image.new("L", (N, N), 0)
    ImageDraw.Draw(hm).polygon(heart_poly(hx, hy + 128 * U, 108 * U), fill=255)
    rib = Image.new("L", (N, N), 0)
    ImageDraw.Draw(rib).polygon([at(q, 0.34, -0.05), at(q, 0.54, -0.05),
                                 at(q, 0.54, 0.12), at(q, 0.34, 0.12)], fill=255)
    both = Image.new("L", (N, N), 0)
    both.paste(hm, (0, 0)); both.paste(rib, (0, 0))
    img = glow_under(img, both, NEON, 38 * U, 150)
    lay = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    lay.paste(NEON + (255,), (0, 0), both)
    return Image.alpha_composite(img, lay)


OPTIONS = [
    ("方案 1 · 夜信", "밤편지：夜里的信，火漆是霓虹心", v1_night_letter),
    ("方案 2 · 调色盘", "Palette：颜料点用淡紫与霓虹黄", v2_palette),
    ("方案 3 · 音符", "UAENA 标志里的音符，单独放大", v3_note),
    ("方案 4 · 花束", "一束丁香，霓虹黄缎带扎起", v4_bouquet),
    ("方案 5 · 心星", "一颗心，右上角一道霓虹星芒", v5_heart_star),
    ("方案 6 · 书与心", "摊开的书 + 霓虹心书签", v6_book_heart),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    imgs = []
    for name, desc, fn in OPTIONS:
        im = fn()
        png = OUT / (name.split(" · ")[0] + ".png")
        im.resize((1024, 1024), Image.LANCZOS).save(png, optimize=True)
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
    sd.text((PAD + 118, PAD - 4), "· 图标方案（第三批 · 歌曲意象）", font=f_cjk_b, fill=(42, 35, 64))
    sd.text((PAD + 560, PAD + 6), "夜信 / Palette / 音符 / 花束 / 心星 / 书与心", font=f_cjk, fill=(120, 108, 150))

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

    out = HERE / "方案对照3.png"
    sheet.save(out, optimize=True)
    print("对照图 ->", out, sheet.size)


if __name__ == "__main__":
    main()
