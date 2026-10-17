#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""라일락 — Plate III · 桌面图版（2560 × 1600）

把工作台界面的那层「光」离线算成一张大图，再叠上一枝丁香。
光用与着色器同一套算法（域扭曲 FBM），所以屏幕上的背景和这张图是同一个东西。

  python make_wallpaper.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
FONTS = Path("E:/WorkBuddy/downloads/fonts")
SYS = Path("C:/Windows/Fonts")

W, H = 2560, 1600
CW, CH = W // 2, H // 2          # 光场在半分辨率下计算，再放大——玻璃的模糊本来就掩盖了这点损失

LILAC_HI = (176, 150, 236)
LILAC_LO = (92, 63, 168)
NEON = (228, 255, 63)
random.seed(20210325)            # LILAC 发行日


# --------------------------------------------------------------------- 噪声
def _hash(ix, iy, seed):
    u = np.uint64
    with np.errstate(over="ignore"):
        n = (ix.astype(u) * u(374761393) + iy.astype(u) * u(668265263)
             + u(seed & 0xFFFFFFFF) * u(1442695040888963407))
        n = (n ^ (n >> u(13))) * u(1274126177)
        n = n ^ (n >> u(16))
    return (n & u(0xFFFFFF)).astype(np.float64) / 16777215.0


def noise2(x, y, seed):
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = x - ix, y - iy
    u = fx * fx * (3.0 - 2.0 * fx)
    v = fy * fy * (3.0 - 2.0 * fy)
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1.0, iy, seed)
    c = _hash(ix, iy + 1.0, seed)
    d = _hash(ix + 1.0, iy + 1.0, seed)
    return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v


def fbm(x, y, seed, octaves=4):
    f = 0.0
    amp = 0.5
    norm = 0.0
    ca, sa = 0.80, 0.60            # 层间旋转，打散轴向条纹
    for i in range(octaves):
        f += amp * noise2(x, y, seed + i * 37)
        norm += amp
        x, y = (ca * x - sa * y) * 2.03, (sa * x + ca * y) * 2.03
        amp *= 0.5
    return f / norm


def light_field(t=0.0):
    """与 bg-shader.js 同构：两级域扭曲，输出 0~1 的标量场。"""
    yy, xx = np.mgrid[0:CH, 0:CW].astype(np.float64)
    u = (2.0 * xx - CW) / CH
    v = (2.0 * yy - CH) / CH
    u *= 1.25
    v *= 1.25

    q1 = fbm(u, v + t, 11)
    q2 = fbm(u + 5.2 - t, v + 1.3, 23)
    r1 = fbm(u + 1.35 * q1 + 1.7 + 0.7 * t, v + 1.35 * q1 + 9.2, 41)
    r2 = fbm(u + 1.35 * q2 + 8.3 - 0.6 * t, v + 1.35 * q2 + 2.8, 59)
    f = np.clip(fbm(u + 1.15 * r1, v + 1.15 * r2, 71), 0.0, 1.0)
    return u, v, f


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def render_field():
    u, v, f = light_field(t=0.0)
    c0 = np.array([0.984, 0.976, 0.996])
    c1 = np.array([0.906, 0.871, 0.973])
    c2 = np.array([0.792, 0.729, 0.925])
    c3 = np.array([0.925, 0.976, 0.463])

    col = c0 + (c1 - c0) * smoothstep(0.22, 0.88, f)[..., None]
    col = col + (c2 - col) * (smoothstep(0.56, 1.10, f) * 0.56)[..., None]
    d = np.sqrt(((u - 0.95) * 0.85) ** 2 + (v - 0.62) ** 2)
    neon = smoothstep(0.62, 0.98, f) * (1.0 - smoothstep(0.10, 1.05, d))
    col = col + (c3 - col) * (neon * 0.24)[..., None]

    # 轻微垂直衰减 + 抖动去色带
    col *= (1.0 - 0.042 * (np.mgrid[0:CH, 0:CW][0] / CH))[..., None]
    col += (np.random.random(col.shape) - 0.5) * (1.6 / 255.0)
    img = Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8), "RGB")
    return img.resize((W, H), Image.LANCZOS)


# --------------------------------------------------------------------- 丁香
def draw_panicle(img, base_x, base_y, height, max_r, count):
    """一枝丁香：主轴 + 放射小枝 + 十字花冠，整体收成一个圆锥（panicle）。"""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    stem = (86, 64, 140, 165)

    def axis(k):
        return base_x + math.sin(k * 1.9) * height * 0.045, base_y - k * height

    pts = [axis(i / 79.0) for i in range(80)]
    d.line(pts, fill=stem, width=3, joint="curve")

    for _ in range(count):
        k = random.random() ** 0.80                      # 下部更密
        ax, ay = axis(k)
        r = max_r * (1.0 - k) ** 0.92                    # 锥形收口
        a = random.uniform(0.0, 2.0 * math.pi)
        rr = r * math.sqrt(random.random())
        fx = ax + math.cos(a) * rr
        fy = ay + math.sin(a) * rr * 0.82
        d.line([(ax, ay), (fx, fy)], fill=stem, width=1, joint="curve")

        taper = 1.0 - k * 0.45
        R = (8.0 + 6.0 * random.random()) * taper
        D = R * 0.86
        neon = random.random() < 0.055                   # 约 5.5% 用霓虹黄
        col = NEON + (232,) if neon else (
            (255, 255, 255, 216) if random.random() < 0.62 else (234, 224, 253, 206))
        for ang2 in (-90, 0, 90, 180):
            a2 = math.radians(ang2)
            px, py = fx + math.cos(a2) * D, fy + math.sin(a2) * D
            d.ellipse([px - R, py - R, px + R, py + R], fill=col)
        cr = R * 0.34
        d.ellipse([fx - cr, fy - cr, fx + cr, fy + cr], fill=(150, 122, 214, 120))

    return Image.alpha_composite(img.convert("RGBA"), lay.filter(ImageFilter.GaussianBlur(0.5)))


# --------------------------------------------------------------------- 文字
def spaced(d, xy, text, font, fill, track):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + track
    return x


def main():
    img = render_field().convert("RGBA")

    # 两枝丁香：一枝主，一枝次，错开高度
    img = draw_panicle(img, W * 0.700, H * 1.00, H * 0.80, 132, 300)
    img = draw_panicle(img, W * 0.845, H * 1.06, H * 0.60, 96, 190)

    d = ImageDraw.Draw(img, "RGBA")
    ink = (42, 35, 64, 235)
    ink2 = (86, 74, 122, 200)

    f_kr = ImageFont.truetype(str(SYS / "malgun.ttf"), 186)
    f_lat = ImageFont.truetype(str(FONTS / "Italiana-Regular.ttf"), 56)
    f_mono = ImageFont.truetype(str(FONTS / "JetBrainsMono-400.ttf"), 20)
    f_cjk = ImageFont.truetype(str(SYS / "simsun.ttc"), 30)

    # 左下：标题块
    x0, y0 = 176, H - 512
    spaced(d, (x0, y0), "라일락", f_kr, ink, 20)
    spaced(d, (x0 + 8, y0 + 244), "L I L A C", f_lat, ink2, 12)
    d.line([(x0 + 8, y0 + 340), (x0 + 420, y0 + 340)], fill=(120, 96, 176, 130), width=1)
    d.text((x0 + 8, y0 + 366), "组会工作台 · 论文与幻灯片的对照阅读", font=f_cjk, fill=ink2)

    # 右下：图版标记
    d.text((W - 176 - 430, 96), "PLATE III   LILAC   2560 x 1600", font=f_mono, fill=(104, 92, 140, 165))

    # 左上：一枚极小的花冠，作签名
    cx, cy, R, D = 196, 168, 15, 13
    for ang, col in ((-90, (255, 255, 255, 220)), (0, (255, 255, 255, 220)),
                     (90, (255, 255, 255, 220)), (180, NEON + (235,))):
        a = math.radians(ang)
        px, py = cx + math.cos(a) * D, cy + math.sin(a) * D
        d.ellipse([px - R, py - R, px + R, py + R], fill=col)
    d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(92, 63, 168, 200))

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / "라일락-桌面图版.png"
    img.convert("RGB").save(png, optimize=True)
    print("wallpaper ->", png, "(%dx%d, %.1f MB)" % (img.width, img.height, png.stat().st_size / 1048576))


if __name__ == "__main__":
    main()
