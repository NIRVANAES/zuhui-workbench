# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本 —— 「组会工作台」精简版（单 exe，约 44 MB）。

用法（在本仓库根目录）：
    python -m PyInstaller --clean --noconfirm build/组会工作台.spec
产物在 dist/组会工作台.exe。

⚠️ 路径全部基于 SPECPATH 推导，**不要写死绝对路径** —— 写死的话，
    仓库换台机器 clone 下来就构建失败（本项目就为此返工过一次）。

exe 里已经内嵌：组会工作台.html、编辑器/、icon、PDFium、jieba 词典。
所以把它单独拷到任何一台 Windows 上都能跑，不需要旁边再有别的文件。
"""
import os

from PyInstaller.utils.hooks import collect_all

# ⚠️ SPECPATH 是 **spec 文件所在的目录**（PyInstaller 6.22 实测：值为 .../开源版/build，
#    不是 spec 文件本身的路径），所以直接用它、不要再 dirname。
#    写死绝对路径会让仓库换台机器 clone 就构建失败（本项目为此返工过一次）。
import os

BASE = os.path.abspath(SPECPATH)              # = build/
APP = os.path.join(BASE, "..", "app")         # = 仓库根/app

datas = [(os.path.join(APP, "组会工作台.html"), "."),
         (os.path.join(APP, "icon.ico"), "."),
         (os.path.join(APP, "编辑器"), "编辑器")]
binaries = []
hiddenimports = ['webview.platforms.edgechromium', 'clr_loader']
tmp_ret = collect_all('pptx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# pypdf：从论文 PDF 里取插图用（纯 Python，体积小；PyMuPDF 53MB 太大不塞）
tmp_ret = collect_all('pypdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# pypdfium2：**按页渲染**论文 PDF（插图「按页框选」用）。
# 为什么值得加这 7.4 MB：直接抽 PDF 内嵌位图会把一张多子图 Figure 拆成碎片
# （实测 Figure 3 = 6 个独立对象），渲染整页再框选才是「所见即所得」，
# 顺带把「纯矢量图取不到」也解决了。授权：Apache-2.0 + PDFium BSD-3-Clause。
tmp_ret = collect_all('pypdfium2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pypdfium2_raw')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# jieba：中文分词（标签自动识别用）。
# 只带核心：dict.txt(4.8MB) + finalseg(3.6MB)；我们只用 jieba.cut / add_word。
#
# ⚠️ 光过滤 datas 不够！jieba/__init__.py 里有 `import jieba.lac_small.predict`、
#    __main__.py 里有 `import jieba.posseg` —— PyInstaller 会跟踪**函数体内**的 import，
#    于是把 posseg/analyse/lac_small 整个拉进来（实测多塞了 27 个文件、exe 大 10MB）。
#    必须用 excludes 从模块图上剔除：
tmp_ret = collect_all('jieba')
_SKIP = ('/posseg/', '/analyse/', '/lac_small/', '/__pycache__/')
datas += [d for d in tmp_ret[0]
          if not any(s in d[0].replace('\\', '/') for s in _SKIP)]
binaries += tmp_ret[1]
hiddenimports += ['jieba', 'jieba.finalseg']   # 写成 jieba.finalseg，否则打包日志会报一句 ERROR


a = Analysis(
    [os.path.join(APP, "desktop.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['jieba.posseg', 'jieba.analyse', 'jieba.lac_small'],
    noarchive=False,
    optimize=2,
)

# ⚠️ 光靠上面的 excludes 与 _SKIP 过滤还不够（2026-10-16 实测）：
#    新版 pyinstaller-hooks-contrib 自带 hook-jieba.py，它把 jieba 的数据文件
#    直接加进了最终的 a.datas，绕过了上面 collect_all('jieba') 的那道过滤
#    （那道只筛 collect_all 的返回值，管不到 hook 自己塞进来的东西）。
#    实测因此多塞 27 个文件（lac_small 22 + posseg 4 + analyse 1），exe 白胖约 3 MB。
#    在 Analysis 之后、进 PYZ 之前再筛一遍 —— 与 hooks 版本无关，永久有效。
_SKIP2 = ("/lac_small/", "/posseg/", "/analyse/")
_before = len(a.datas)
a.datas = [d for d in a.datas
           if not any(s in str(d[0]).replace("\\", "/")
                      or s in str(d[1]).replace("\\", "/") for s in _SKIP2)]
print("[spec] jieba 冗余数据文件剔除 %d 个（datas %d -> %d）"
      % (_before - len(a.datas), _before, len(a.datas)))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='组会工作台',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(APP, "icon.ico"),
)
