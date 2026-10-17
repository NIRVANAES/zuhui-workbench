#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 源码/minimal.src.html 里的外部引用内联，生成**单文件**的 组会工作台.html。

用法（在本文件所在目录执行）：
    python build_minimal.py                生成 ../组会工作台.html
    python build_minimal.py --check        只校验「重建结果与现有成品是否逐字节一致」

为什么要有这一步：单文件 HTML 双击就能用（不依赖任何服务器），但 2.4 MB 的成品
没法直接编辑。所以维护时改 vendor/*.js 或 minimal.src.html，再用这个脚本内联回去。

⚠️ 只内联 `vendor/` 下的引用，其它原样保留 —— 页面里 `icon.png` 这种相对路径
   依赖 exe 把 HTML 和 ico 放在一起，不是内联目标。
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent
SRC = HERE / "minimal.src.html"
OUT = APP / "组会工作台.html"

_SCRIPT = re.compile(r'<script\s+src="(vendor/[\w./-]+)"\s*>\s*</script>')
_STYLE = re.compile(r'<link\s+rel="stylesheet"\s+href="(vendor/[\w./-]+)"\s*>')


def build(text: str) -> str:
    def sub_script(m):
        f = HERE / m.group(1)
        if not f.is_file():
            sys.exit("找不到 %s" % f)
        return "<script>%s</script>" % f.read_text(encoding="utf-8")

    def sub_style(m):
        f = HERE / m.group(1)
        if not f.is_file():
            sys.exit("找不到 %s" % f)
        return "<style>%s</style>" % f.read_text(encoding="utf-8")

    return _STYLE.sub(sub_style, _SCRIPT.sub(sub_script, text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    a = ap.parse_args()
    text = SRC.read_text(encoding="utf-8")
    out = build(text)
    if a.check:
        cur = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if out == cur:
            print("✅ 重建结果与现有成品逐字节一致（%d 字符）" % len(out))
            return 0
        print("❌ 不一致：重建 %d 字符 / 现有 %d 字符" % (len(out), len(cur)))
        for i, (x, y) in enumerate(zip(out, cur)):
            if x != y:
                print("   首个差异在第 %d 字符：重建 %r vs 现有 %r" % (i, out[i:i+40], cur[i:i+40]))
                break
        return 1
    OUT.write_text(out, encoding="utf-8")
    print("built -> %s  (%d 字符，内联 %d 个库)"
          % (OUT, len(out), len(_SCRIPT.findall(text)) + len(_STYLE.findall(text))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
