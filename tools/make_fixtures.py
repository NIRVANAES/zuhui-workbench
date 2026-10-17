# -*- coding: utf-8 -*-
"""生成自检用的最小夹具 —— 纯本地生成，无任何版权问题。

为什么不用现成的样例文件：
  仓库里原本引用的 demo/demo_slides.pptx 与 demo_paper.pdf 分别来自
  python-pptx 官方测试集和一篇真实论文（有版权），**不能**随开源仓库分发。
  自检其实只需要「一份能解析的 PPTX + 一份能渲染的 PDF」，所以这里现造：
    · demo.pptx —— 2 页、每页一个文本框（python-pptx，已是本项目依赖）
    · demo.pdf  —— 1 页 A4 白纸（Pillow 把白图另存为 PDF，已是本项目依赖）
  两者都是 KB 级，且是确定性输出，便于复现自检结果。

用法（在仓库任意位置）：
    python tools/make_fixtures.py              # 缺什么造什么
    python tools/make_fixtures.py --force      # 强制重造
"""
from __future__ import annotations

import argparse
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "fixtures"


def make_pptx(path: pathlib.Path) -> None:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    # 造 4 页：自检脚本要「翻到第 3 页」当 soft refresh 的探针，页数必须 ≥ 3
    for i in range(4):
        slide = prs.slides.add_slide(prs.slide_layouts[6])      # 空白版式
        box = slide.shapes.add_textbox(Inches(0.6), Inches(0.6),
                                       Inches(6), Inches(1.2))
        box.text_frame.text = "自检幻灯片 第 %d 页" % (i + 1)
    prs.save(str(path))


def make_pdf(path: pathlib.Path) -> None:
    # PIL 支持把图像另存为 PDF，产出的是一页「图片型 PDF」，
    # pypdf 与 pypdfium2 都能正常打开与渲染。
    from PIL import Image

    Image.new("RGB", (595, 842), "white").save(str(path), "PDF")


def ensure(force: bool = False) -> dict:
    """确保夹具存在，返回各文件路径（缺的就地生成）。"""
    OUT.mkdir(exist_ok=True)
    made = []
    for name, fn in (("demo.pptx", make_pptx), ("demo.pdf", make_pdf)):
        p = OUT / name
        if p.is_file() and not force:
            continue
        fn(p)
        made.append(name)
    return {"dir": OUT, "made": made,
            "pptx": OUT / "demo.pptx", "pdf": OUT / "demo.pdf"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已存在也重造")
    a = ap.parse_args()
    r = ensure(a.force)
    for name in ("demo.pptx", "demo.pdf"):
        p = pathlib.Path(r["dir"]) / name
        print("  %-10s %8d 字节  %s" % (name, p.stat().st_size, p))
    print("  新生成：%s" % (", ".join(r["made"]) or "（都已在，无需重造）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
