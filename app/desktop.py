#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""组会工作台 · 桌面版

用一个原生窗口装载 组会工作台.html，走 Windows 自带的 WebView2（Edge 内核），
没有地址栏、没有标签页，双击即用。

  python desktop.py              正常启动
  python desktop.py --selftest   开窗 → 自检 → 自动关闭（用于构建后验证）

两个关键点：
1. pywebview 的 private_mode 默认为 True（临时 profile），会导致每次启动
   IndexedDB 都被清空 —— 组会记录全丢。必须显式关掉并指定持久化目录。
2. 页面里「打开 / 另存为」按钮依赖 js_api：Blob 以 base64 传过来，这里落地成
   真实文件再用系统默认程序打开（PPT 用 PowerPoint/WPS 打开才看得到完整效果）。
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import io
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import webview

APP_NAME = "组会工作台"
# 界面版本标记：只用于让用户一眼确认「现在开的这一版含哪些改动」。
# 每次动前端（app.css / app.js）都改一下这里，再重打包。
BUILD_TAG = "UI 1017m"
HTML_NAME = "组会工作台.html"


def app_dir() -> Path:
    """可执行文件所在目录（打包后）或脚本所在目录（开发时）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_html() -> Path | None:
    """优先用 exe 同级的 HTML（方便单独替换），退回打包进 exe 的那份。"""
    cands = [app_dir() / HTML_NAME]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / HTML_NAME)
    for p in cands:
        if p.exists():
            return p
    return None


def find_icon() -> Path | None:
    for base in (app_dir(), Path(getattr(sys, "_MEIPASS", app_dir()))):
        p = base / "icon.ico"
        if p.exists():
            return p
    return None


def data_dir() -> Path:
    """浏览器数据目录：优先放 exe 旁边（整个文件夹可拷走），不可写则退到 LOCALAPPDATA。"""
    beside = app_dir() / "数据"
    try:
        beside.mkdir(parents=True, exist_ok=True)
        probe = beside / ".w"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
        return beside
    except Exception:
        fallback = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def fit_window() -> tuple[int, int]:
    """按屏幕尺寸给个合适的初始窗口 —— 别比屏幕还大（小屏笔记本上会跑到屏幕外）。"""
    try:
        u = ctypes.windll.user32
        sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    except Exception:
        sw, sh = 1440, 900
    return min(1440, max(960, sw - 120)), min(900, max(620, sh - 120))


def _log(*parts) -> None:
    """打包成 --windowed 后 sys.stdout 可能是 None，print 会直接抛异常；这里双写。"""
    line = " ".join(str(p) for p in parts)
    try:
        if sys.stdout:
            print(line, flush=True)
    except Exception:
        pass
    try:
        p = app_dir() / "_selftest.log"
        # ⚠️ 2026-10-17 复查：这个文件原来只追加、没有上限，而且**每次正常启动**都会写
        #    （_editor_serve 会记一行「编辑器已就绪」）。名字叫 selftest 却天天被正常使用写，
        #    长期会慢慢变大。超过 256 KB 就重开一份 —— 排查够用，也不会长成垃圾。
        if p.is_file() and p.stat().st_size > 256 * 1024:
            p.unlink()
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _safe_name(name: str) -> str:
    """去掉 Windows 文件名非法字符，保留中文与空格。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(name or "")).strip(" .")
    return s or "file"


# ---------------------------------------------------------------------------
# 说明：这里原本是「腾讯文档 editor_sdk」引擎的接入层（本机扫描 / 拉起 / 代理 /
# 保存回写）。2026-10-17 按要求**整体移除**：PPT 的编辑改走阅读页顶栏的
# 「打开」按钮，交给系统的 PowerPoint / WPS，改完回来点「换 PPT」即可。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 内置幻灯片编辑器（VibeOffice · Lectern，Apache-2.0）
#
# 为什么要在本地起一个 HTTP 服务，而不是直接 iframe 打开文件：
#   它是按「普通网站」写的 —— 用相对路径加载几十个 JS、字体和 i18n JSON，
#   而 WebView2 在 file:// 下会拦掉这些子资源（跨源 / MIME 判定），页面起不来。
#   所以这里在本机回环地址起一个只读静态服务，把打包进 exe 的 编辑器/ 目录发出去。
#
# 安全边界：只绑 127.0.0.1、只允许 GET/HEAD、路径必须落在 编辑器/ 目录内（防 .. 穿越）。
# 文档字节不过这个服务 —— 由页面用 postMessage 直接交给 iframe，磁盘上不留副本。
# ---------------------------------------------------------------------------
_EDITOR_LOCK = threading.Lock()
_EDITOR_URL = ""


def _editor_root() -> Path | None:
    """找到 编辑器/ 目录：优先 exe 内解压出来的那份，其次源码目录。"""
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(Path(meipass))
    bases.append(app_dir())
    for b in bases:
        p = b / "编辑器"
        if (p / "lectern" / "index.html").is_file():
            return p
    return None


class _EditorHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    root: Path | None = None

    def log_message(self, *a):                     # 别把每条请求都写进 stderr
        pass

    def _send(self, code: int, body: bytes, ctype: str, cache: str = "max-age=3600"):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve()

    def _serve(self):
        root = self.root
        if root is None:
            return self._send(503, b"editor not bundled", "text/plain; charset=utf-8", "no-store")
        rel = urllib.parse.unquote(self.path.split("?")[0].split("#")[0]).lstrip("/")
        if not rel or rel.endswith("/"):
            rel += "lectern/index.html"
        try:
            f = (root / rel).resolve()
            f.relative_to(root.resolve())          # 越界直接拒绝
        except Exception:
            return self._send(403, b"forbidden", "text/plain; charset=utf-8", "no-store")
        if not f.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8", "no-store")
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if f.suffix.lower() in (".js", ".mjs"):
            ctype = "application/javascript; charset=utf-8"
        elif f.suffix.lower() == ".json":
            ctype = "application/json; charset=utf-8"
        elif f.suffix.lower() in (".html", ".htm"):
            ctype = "text/html; charset=utf-8"
        elif f.suffix.lower() == ".css":
            ctype = "text/css; charset=utf-8"
        try:
            data = f.read_bytes()
        except Exception as e:
            return self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8", "no-store")
        self._send(200, data, ctype)


def _editor_serve() -> str:
    """懒启动编辑器静态服务，返回它的基地址（失败返回空串）。"""
    global _EDITOR_URL
    if _EDITOR_URL:
        return _EDITOR_URL
    with _EDITOR_LOCK:
        if _EDITOR_URL:
            return _EDITOR_URL
        root = _editor_root()
        if root is None:
            _log("编辑器资源缺失：找不到 编辑器/lectern/index.html")
            return ""
        try:
            handler = type("_H", (_EditorHandler,), {"root": root})
            srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _EDITOR_URL = "http://127.0.0.1:%d" % srv.server_address[1]
            _log("编辑器已就绪 %s（%s）" % (_EDITOR_URL, root))
        except Exception as e:
            _log("编辑器服务启动失败: %s" % e)
            return ""
    return _EDITOR_URL


# ---------------------------------------------------------------------------
# 按页渲染（pypdfium2）—— 解决「一张 Figure 被拆成好几块」
#
# 为什么需要它：PDF 里一张多子图 Figure 常由**多个位图对象**拼成。实测
# arXiv-1905.02315 的 Figure 3 就是 6 个独立对象（尺寸还几乎一样），
# 直接抽对象只能拿到碎片，插进幻灯片自然「四分五裂」。
# 渲染整页再框选，拿到的一定是你眼睛看到的那张图 —— 顺带把「纯矢量图取不到」
# 这个老限制也一并解决了。
#
# 授权：pypdfium2 = Apache-2.0，内含 PDFium = BSD-3-Clause，都可再分发。
# 体积：pdfium.dll 约 7.4 MB（实测），可接受。
# ---------------------------------------------------------------------------
_PDF_DOC: dict = {"key": None, "doc": None}
_MAX_PAGE_THUMBS = 40


def _pdf_doc(raw: bytes):
    """按内容哈希缓存已打开的 PDF —— 同一份论文来回翻页时不用反复解析。

    ⚠️ 顺序很关键：**先建新文档，成功后再替换并关掉旧的**。
    反过来写（先关旧再建新）会在解析失败时把缓存留成一个**已关闭**的文档，
    之后所有取图调用都会莫名其妙地失败 —— 这个 bug 真踩过。
    """
    key = hashlib.md5(raw).hexdigest()
    if _PDF_DOC["key"] == key and _PDF_DOC["doc"] is not None:
        return _PDF_DOC["doc"]
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(raw)            # 失败就在这里抛，缓存保持原样
    old = _PDF_DOC["doc"]
    _PDF_DOC["key"], _PDF_DOC["doc"] = key, doc
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    return doc

# 我们插进幻灯片的图都打这个标记 —— 重排版式时只动我们自己插的，PPT 自带的图不碰
_IMG_TAG = "__wb_fig__"

# ---------------------------------------------------------------------------
# 从论文 / PPT 里猜标签
#
# **只输出中文标签**。论文基本都是英文写的，若直接把英文词当标签吐出来，
# 用户看到的是一堆 "metasurface / terahertz" —— 标签体系就散了。
# 所以英文术语先查 `_EN_ALIAS` 折成中文再统计，查不到的一律丢掉。
#   ① 先拿用户**自己用过的标签**去原文里数（中文直接数，英文别名也算，
#      否则英文论文里「用过」这条路径永远是空的）；
#   ② 科研词表里的中文词直接数一遍（jieba 缺席时这条尤其顶用）；
#   ③ 再补中文分词候选：jieba 优先（带自定义科研词表），缺了就退到 2~5 字片段法。
# 排序时词表 / 别名命中的 +2 加权，让专业词压过泛用词。
# ---------------------------------------------------------------------------
_JIEBA_READY = False

_TAG_STOP = set("""
本文 我们 方法 结果 因此 由于 可以 进行 研究 分析 表明 以及 但是 如果 这个 一种 通过
得到 具有 不同 相关 影响 问题 工作 论文 数据 实验 模型 条件 情况 时间 过程 系统 结构
作用 关系 提高 增加 降低 变化 性质 材料 性能 参数 其中 并且 而且 为了 对于 关于 基于
采用 使用 实现 给出 所示 见图 如图 一个 这些 那些 这种 那种 什么 怎么 非常 十分 更加
摘要 引言 结论 关键词 参考文献 致谢 目录 附录 图表 通讯作者 收稿日期 基金项目 作者简介
正文 章节 表格 公式 符号 变量 单位 数值 范围 效果 程度 能力 方面 部分 内容 方式 目标
提出 发现 观察 验证 证实 支持 认为 估计 假设 定义 描述 计算 求解 处理 获得 达到 呈现
相关 类似 相同 差异 区别 特征 特点 优势 局限 不足 意义 价值 前景 趋势 现状 背景
切换 转换 变化 增大 减小 上升 下降 出现 存在 保持 维持 满足 达到 超出 高于 低于
频段 波段 区间 位置 方向 角度 距离 尺寸 数量 总量 波形 曲线 峰值 均值
较大 较小 主要 重要 基本 一般 直接 间接 进一步 同时 之后 之前 目前 现在 已经 开始
结束 需要 可能 应该 必须 能够 不能 没有 就是 还是 这样 那样 而且 或者 因为 所以 例如
包括 分别 其中 二者 两者 由此 从而 进而 总之 综上 可见 得出 说明 表示 认为 提出 建立
研究 讨论 综述 进展 应用 技术 理论 数值 模拟 计算 测量 观测 记录 绘制 对比 比较
the for and with that this from are was were has have been which their they can not
using used study studies result results method methods show shows shown paper papers
data model models figure table section eq equation ref reference et al also than then
more most some such other others these those there where when what how why who whom
""".split())

# 泛用中文词（第二道）—— 实测 jieba 会把「平均」「基线」「堆叠」这种词当候选吐出来，
# 它们在一篇论文里出现次数不少，却完全不能代表这篇论文讲什么。
# ⚠️ 别把专业词误伤进来：相位 / 效率 / 频率 / 表面 / 结构 / 波段 / 聚焦 / 损耗
#    这些都是正经标签，不能进这张表。
_TAG_STOP |= set("""
平均 基线 堆叠 均值 总和 累计 梯度 斜率 曲线 直线 平面 二维 三维 初始 最终
大小 数量 位置 方向 部分 全部 整体 对应 相同 相等 附近 周围 左右 上下 前后
内部 外部 顶部 底部 中间 中心 区域 范围 距离 间隔 尺寸 长度 宽度 高度 厚度
面积 体积 质量 重量 比例 比值 倍数 差值 误差 偏差 上限 下限 各自 互相 共同
次要 基础 典型 常见 特殊 普通 简单 复杂 容易 困难 快速 缓慢 稳定 可靠
精确 准确 清晰 明显 显著 微弱 强烈 此外 然而 例如 比如 所谓 而言 来说
""".split())


# PDF 里 ff/fi/ffi 这些常被排成**连字**（U+FB00~FB06），不还原的话
# "eﬃciency" 会被切成 "ciency"、"Diﬀerentiable" 会被切成 "erentiable"。
_LIGATURES = str.maketrans({
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "ft", "\ufb06": "st",
})


# 科研常用词表：喂给 jieba 当自定义词典。
# 为什么非要有这个 —— jieba 自带词典不认识专业词，实测会把「太赫兹」切成
# 太/赫兹、「超表面」切成 超/表面光。加了这份表之后才切得对。
_ZH_TERMS = """
太赫兹 超表面 超材料 超透镜 光子晶体 等离激元 表面等离激元 波导 谐振腔 微腔 光栅
光开关 调制器 解调器 探测器 激光器 发光二极管 光电探测器 太阳能电池 晶体管 忆阻器
场效应管 集成电路 传感器 生物传感器 微流控 光谱 光谱仪 折射率 介电常数 磁导率
透射率 反射率 吸收率 消光比 调制深度 品质因子 插入损耗 色散 群速度 波前 相位 偏振
双折射 手性 干涉 衍射 全息 慢光 光镊 非线性光学 二次谐波 三次谐波 频率梳 锁模
飞秒 皮秒 纳秒 泵浦 探测光 拓扑光子学 纳米光子学 量子光学 单光子 纠缠 相干 退相干
相变材料 相变存储器 异质结 同质结 量子阱 量子点 纳米线 纳米片 纳米带 纳米棒
二维材料 过渡金属硫化物 石墨烯 氧化石墨烯 碳纳米管 钙钛矿 钙钛矿太阳能电池
氮化镓 碳化硅 硅基光子学 氧化物 硫系化合物 金属有机框架 单晶 多晶 非晶 薄膜 外延
掺杂 退火 钝化 刻蚀 光刻 键合 转移 堆叠 应变 晶格 缺陷 空位 界面 势垒 能带 带隙
态密度 费米面 布里渊区 载流子 迁移率 载流子寿命 激子 声子 极化子 铁电 铁磁 反铁磁
超导 拓扑绝缘体 韦尔半金属 自旋电子学 磁各向异性 电畴 畴壁 相变 亚稳态
第一性原理 密度泛函理论 分子动力学 有限元 时域有限差分 蒙特卡洛 紧束缚 格林函数
机器学习 深度学习 神经网络 卷积神经网络 循环神经网络 注意力机制 强化学习 迁移学习
生成对抗网络 反向传播 梯度下降 优化算法 遗传算法 粒子群算法 贝叶斯优化 高斯过程
代理模型 数据驱动 超参数 过拟合 正则化 交叉验证 特征提取 降维 聚类 分类 回归
主成分分析 支持向量机 随机森林 决策树 集成学习 数字孪生 逆向设计 拓扑优化
灵敏度 分辨率 响应时间 阈值 鲁棒性 可扩展性 可重复性 对比度 信噪比 效率 带宽
数值模拟 理论分析 实验验证 表征 显微镜 扫描电子显微镜 透射电子显微镜 原子力显微镜
X射线衍射 拉曼光谱 光致发光 椭偏仪 霍尔效应 四探针 电化学 循环伏安 催化剂 电催化
储能 锂电池 超级电容器 燃料电池 热电 压电 摩擦电 微纳加工 柔性电子 可穿戴
"""


# 英文术语 → 中文标签。
# 为什么要这张表：论文基本都是英文写的，若直接把英文词当标签吐出来，用户看到的是
# 一堆 "metasurface / terahertz" —— 标签体系就散了。折成中文才能和用户手打的标签对齐。
# 键用小写；多词短语用空格或连字符都行（匹配时统一按 [\s-]+ 处理）。
_EN_ALIAS = {
    "terahertz": "太赫兹", "thz": "太赫兹", "t-ray": "太赫兹", "t-rays": "太赫兹",
    "metasurface": "超表面", "metasurfaces": "超表面", "meta-surface": "超表面",
    "metamaterial": "超材料", "metamaterials": "超材料",
    "metalens": "超透镜", "metalenses": "超透镜",
    "photonic crystal": "光子晶体", "photonic crystals": "光子晶体",
    "plasmonic": "等离激元", "plasmonics": "等离激元", "plasmon": "等离激元",
    "surface plasmon": "表面等离激元", "surface plasmon polariton": "表面等离激元",
    "waveguide": "波导", "waveguides": "波导",
    "resonator": "谐振腔", "resonators": "谐振腔",
    "microcavity": "微腔", "microcavities": "微腔",
    "grating": "光栅", "gratings": "光栅",
    "optical switch": "光开关", "optical switching": "光开关",
    "all-optical switching": "光开关", "photoswitch": "光开关",
    "modulator": "调制器", "modulators": "调制器",
    "photodetector": "光电探测器", "photodetectors": "光电探测器",
    "photodiode": "光电探测器",
    "detector": "探测器", "detectors": "探测器",
    "laser": "激光器", "lasers": "激光器",
    "light-emitting diode": "发光二极管", "light emitting diode": "发光二极管",
    "solar cell": "太阳能电池", "solar cells": "太阳能电池",
    "photovoltaic": "太阳能电池",
    "transistor": "晶体管", "transistors": "晶体管",
    "memristor": "忆阻器", "memristors": "忆阻器",
    "biosensor": "生物传感器", "sensor": "传感器", "sensors": "传感器",
    "microfluidic": "微流控", "microfluidics": "微流控",
    "spectroscopy": "光谱", "spectrometer": "光谱仪", "spectrum": "光谱",
    "refractive index": "折射率",
    "dielectric constant": "介电常数", "permittivity": "介电常数",
    "permeability": "磁导率",
    "transmittance": "透射率", "reflectance": "反射率",
    "extinction ratio": "消光比", "modulation depth": "调制深度",
    "quality factor": "品质因子", "q-factor": "品质因子",
    "insertion loss": "插入损耗", "dispersion": "色散",
    "group velocity": "群速度", "wavefront": "波前",
    "polarization": "偏振", "polarisation": "偏振",
    "birefringence": "双折射", "chirality": "手性", "chiral": "手性",
    "interference": "干涉", "diffraction": "衍射",
    "holography": "全息", "hologram": "全息", "holographic": "全息",
    "slow light": "慢光", "optical tweezer": "光镊", "optical tweezers": "光镊",
    "nonlinear optics": "非线性光学", "nonlinear optical": "非线性光学",
    "second harmonic": "二次谐波", "third harmonic": "三次谐波",
    "frequency comb": "频率梳", "mode-locked": "锁模", "mode locking": "锁模",
    "femtosecond": "飞秒", "picosecond": "皮秒", "nanosecond": "纳秒",
    "topological photonics": "拓扑光子学", "nanophotonics": "纳米光子学",
    "quantum optics": "量子光学", "single-photon": "单光子", "single photon": "单光子",
    "entanglement": "纠缠", "decoherence": "退相干",
    "phase-change material": "相变材料", "phase change material": "相变材料",
    "phase-change": "相变材料", "phase change": "相变材料",
    "heterojunction": "异质结", "heterostructure": "异质结",
    "quantum well": "量子阱", "quantum dot": "量子点", "quantum dots": "量子点",
    "nanowire": "纳米线", "nanowires": "纳米线", "nanosheet": "纳米片",
    "nanoribbon": "纳米带", "nanorod": "纳米棒", "nanorods": "纳米棒",
    "two-dimensional material": "二维材料", "2d material": "二维材料",
    "transition metal dichalcogenide": "过渡金属硫化物",
    "graphene oxide": "氧化石墨烯", "graphene": "石墨烯",
    "carbon nanotube": "碳纳米管", "carbon nanotubes": "碳纳米管",
    "perovskite": "钙钛矿", "gallium nitride": "氮化镓", "silicon carbide": "碳化硅",
    "silicon photonics": "硅基光子学", "chalcogenide": "硫系化合物",
    "thin film": "薄膜", "thin films": "薄膜", "epitaxial": "外延", "epitaxy": "外延",
    "doping": "掺杂", "doped": "掺杂", "annealing": "退火", "passivation": "钝化",
    "etching": "刻蚀", "lithography": "光刻", "bonding": "键合",
    "lattice": "晶格", "vacancy": "空位", "defect": "缺陷",
    "band gap": "带隙", "bandgap": "带隙", "band structure": "能带",
    "density of states": "态密度", "fermi level": "费米面",
    "brillouin zone": "布里渊区", "carrier lifetime": "载流子寿命",
    "carrier mobility": "迁移率", "mobility": "迁移率",
    "exciton": "激子", "excitons": "激子", "phonon": "声子", "polaron": "极化子",
    "ferroelectric": "铁电", "ferromagnetic": "铁磁", "antiferromagnetic": "反铁磁",
    "superconductor": "超导", "superconducting": "超导",
    "topological insulator": "拓扑绝缘体", "weyl semimetal": "韦尔半金属",
    "spintronics": "自旋电子学", "magnetic anisotropy": "磁各向异性",
    "domain wall": "畴壁",
    "first-principles": "第一性原理", "first principles": "第一性原理",
    "density functional theory": "密度泛函理论",
    "molecular dynamics": "分子动力学", "finite element": "有限元",
    "finite-difference time-domain": "时域有限差分", "fdtd": "时域有限差分",
    "monte carlo": "蒙特卡洛", "green's function": "格林函数",
    "machine learning": "机器学习", "deep learning": "深度学习",
    "neural network": "神经网络", "neural networks": "神经网络",
    "convolutional neural network": "卷积神经网络",
    "attention mechanism": "注意力机制", "reinforcement learning": "强化学习",
    "transfer learning": "迁移学习", "generative adversarial": "生成对抗网络",
    "backpropagation": "反向传播", "gradient descent": "梯度下降",
    "genetic algorithm": "遗传算法", "bayesian optimization": "贝叶斯优化",
    "gaussian process": "高斯过程", "surrogate model": "代理模型",
    "data-driven": "数据驱动", "hyperparameter": "超参数", "hyperparameters": "超参数",
    "overfitting": "过拟合", "regularization": "正则化",
    "cross-validation": "交叉验证", "feature extraction": "特征提取",
    "dimensionality reduction": "降维", "clustering": "聚类",
    "principal component analysis": "主成分分析",
    "support vector machine": "支持向量机", "random forest": "随机森林",
    "decision tree": "决策树", "inverse design": "逆向设计",
    "topology optimization": "拓扑优化", "sensitivity": "灵敏度",
    "response time": "响应时间", "robustness": "鲁棒性", "scalability": "可扩展性",
    "signal-to-noise ratio": "信噪比", "bandwidth": "带宽",
    "numerical simulation": "数值模拟", "characterization": "表征",
    "scanning electron microscope": "扫描电子显微镜",
    "transmission electron microscope": "透射电子显微镜",
    "atomic force microscope": "原子力显微镜",
    "x-ray diffraction": "X射线衍射", "raman": "拉曼光谱",
    "photoluminescence": "光致发光", "ellipsometry": "椭偏仪",
    "hall effect": "霍尔效应", "four-point probe": "四探针",
    "electrochemistry": "电化学", "cyclic voltammetry": "循环伏安",
    "catalyst": "催化剂", "electrocatalysis": "电催化",
    "lithium battery": "锂电池", "supercapacitor": "超级电容器",
    "fuel cell": "燃料电池", "thermoelectric": "热电",
    "piezoelectric": "压电", "triboelectric": "摩擦电",
    "nanofabrication": "微纳加工", "flexible electronics": "柔性电子",
    "wearable": "可穿戴", "metastable": "亚稳态",
    # ---- 材料（最容易缺、又最能代表一篇论文的一类）----
    "lithium niobate": "铌酸锂", "ln": "铌酸锂",
    "silicon nitride": "氮化硅", "sin": "氮化硅",
    "silicon dioxide": "二氧化硅", "silica": "二氧化硅",
    "silicon-on-insulator": "绝缘体上硅", "soi": "绝缘体上硅",
    "silicon": "硅", "germanium": "锗", "gold": "金", "silver": "银",
    "aluminium": "铝", "aluminum": "铝", "copper": "铜", "titanium": "钛",
    "indium tin oxide": "氧化铟锡", "ito": "氧化铟锡",
    "vanadium dioxide": "二氧化钒", "vo2": "二氧化钒",
    "antimony selenide": "硒化锑", "sb2se3": "硒化锑",
    "antimony sulfide": "硫化锑", "sb2s3": "硫化锑",
    "germanium antimony telluride": "锗锑碲", "gst": "锗锑碲", "ge2sb2te5": "锗锑碲",
    "gallium arsenide": "砷化镓", "gaas": "砷化镓",
    "indium phosphide": "磷化铟", "inp": "磷化铟",
    "zinc oxide": "氧化锌", "zno": "氧化锌",
    "titanium dioxide": "二氧化钛", "tio2": "二氧化钛",
    "molybdenum disulfide": "二硫化钼", "mos2": "二硫化钼",
    "tungsten disulfide": "二硫化钨", "ws2": "二硫化钨",
    "hexagonal boron nitride": "六方氮化硼", "hbn": "六方氮化硼",
    "black phosphorus": "黑磷", "phosphorene": "黑磷",
    "liquid crystal": "液晶", "polymer": "聚合物", "dielectric": "介质",
    "noble metal": "贵金属", "metal": "金属",
    "epsilon-near-zero": "近零介电常数", "enz": "近零介电常数",
    "magnetic material": "磁性材料", "oxide": "氧化物",
    # ---- 器件 / 结构 ----
    "phase shifter": "相移器", "phase shifters": "相移器",
    "beam splitter": "分束器", "splitter": "分束器",
    "microring resonator": "微环谐振器", "micro-ring resonator": "微环谐振器",
    "ring resonator": "环形谐振器", "racetrack resonator": "跑道型谐振器",
    "mach-zehnder": "马赫-曾德尔", "mach zehnder": "马赫-曾德尔",
    "interferometer": "干涉仪", "directional coupler": "定向耦合器",
    "multimode interference": "多模干涉", "mmi": "多模干涉",
    "bragg grating": "布拉格光栅", "photonic integrated circuit": "光子集成芯片",
    "pic": "光子集成芯片", "antenna": "天线", "nanoantenna": "纳米天线",
    "multiplexer": "复用器", "demultiplexer": "解复用器",
    "filter": "滤波器", "isolator": "隔离器", "circulator": "环形器",
    "polarizer": "偏振片", "microelectromechanical": "微机电系统", "mems": "微机电系统",
    "slot waveguide": "狭缝波导", "nanobeam": "纳米梁", "nanocavity": "纳米腔",
    "cavity": "微腔", "cavities": "微腔", "nanostructure": "纳米结构",
    "nanoparticle": "纳米颗粒", "nanostripe": "纳米条纹",
    "metagrating": "超光栅", "hyperbolic metamaterial": "双曲超材料",
    # ---- 指标 / 性能 ----
    "crosstalk": "串扰", "on-off ratio": "开关比", "switching energy": "开关能量",
    "energy consumption": "能耗", "footprint": "器件尺寸",
    "modulation efficiency": "调制效率", "figure of merit": "品质因数",
    "tolerance": "容差", "fabrication tolerance": "工艺容差", "yield": "良率",
    "endurance": "耐久性", "cyclability": "循环稳定性", "switching time": "开关时间",
    "switching speed": "开关速度", "data rate": "数据速率", "bit rate": "比特率",
    "throughput": "吞吐量", "loss": "损耗", "transmission loss": "传输损耗",
    "propagation loss": "传输损耗", "reflection loss": "回波损耗",
    "contrast ratio": "对比度", "dynamic range": "动态范围",
    # ---- 物理 / 机理 ----
    "electro-optic": "电光", "electrooptic": "电光", "thermo-optic": "热光",
    "thermooptic": "热光", "all-optical": "全光", "free carrier": "自由载流子",
    "carrier injection": "载流子注入", "carrier depletion": "载流子耗尽",
    "kerr effect": "克尔效应", "saturable absorption": "可饱和吸收",
    "two-photon absorption": "双光子吸收", "evanescent": "倏逝波",
    "multimode": "多模", "single-mode": "单模", "mode coupling": "模式耦合",
    "surface plasmon polariton": "表面等离激元", "localized surface plasmon": "局域表面等离激元",
    "fano resonance": "法诺共振", "whispering gallery": "回音壁",
    "photonic bandgap": "光子带隙", "slow light": "慢光", "optical force": "光力",
    # ---- 工艺 / 表征（补全常用缩写）----
    "electron beam lithography": "电子束光刻", "ebeam lithography": "电子束光刻",
    "chemical vapor deposition": "化学气相沉积", "cvd": "化学气相沉积",
    "sputtering": "溅射", "wafer": "晶圆", "foundry": "代工",
    "cmos-compatible": "CMOS 兼容", "back-end-of-line": "后道工艺",
    "four-wave mixing": "四波混频", "self-phase modulation": "自相位调制",
    "cross-phase modulation": "交叉相位调制", "stimulated emission": "受激辐射",
    "amplified spontaneous emission": "放大自发辐射", "erbium": "铒",
    "erbium-doped": "掺铒", "gain medium": "增益介质", "laser diode": "激光二极管",
    "vertical cavity surface emitting laser": "垂直腔面发射激光器",
    "quantum cascade laser": "量子级联激光器", "frequency comb": "频率梳",
    "optical parametric": "光参量", "supercontinuum": "超连续谱",
    "second-order nonlinearity": "二阶非线性", "third-order nonlinearity": "三阶非线性",
    "nonlinear refractive index": "非线性折射率", "kerr nonlinearity": "克尔非线性",
    "optical bistability": "光学双稳", "optical memory": "光存储",
    "neuromorphic": "类脑计算", "optical computing": "光计算",
    "in-memory computing": "存算一体", "photonic neural network": "光子神经网络",
    "skyrmion": "斯格明子", "magnon": "磁振子", "spin wave": "自旋波",
    "orbital angular momentum": "轨道角动量", "spin angular momentum": "自旋角动量",
    "vortex beam": "涡旋光束", "structured light": "结构光",
    "beam steering": "光束偏转", "lidar": "激光雷达", "holographic display": "全息显示",
    "augmented reality": "增强现实", "virtual reality": "虚拟现实",
}


def _norm_en(s: str) -> str:
    """把英文写法归一成「小写 + 单空格分隔」，用于查表。"""
    return " ".join(p for p in re.split(r"[\s\-]+", s.strip().lower()) if p)


def _en_pattern(word: str) -> str:
    """把 'phase change' 变成同时匹配 'phase change' / 'phase-change' 的正则片段。

    末尾允许一个可选的 s —— 论文里 waveguide / waveguides 混着用，
    不给复数的词表等于漏掉一半命中。
    """
    parts = [p for p in re.split(r"[\s\-]+", word.strip()) if p]
    pat = r"[\s\-]+".join(re.escape(p) for p in parts)
    if parts and parts[-1][-1:].isalpha() and not parts[-1].endswith("s"):
        pat += "s?"
    return pat


def _alias_lookup(key: str):
    """查别名表；复数没直接命中就退一步去掉末尾的 s 再查。"""
    v = _EN_LOOKUP.get(key)
    if v is not None:
        return v
    if len(key) > 3 and key.endswith("s"):
        return _EN_LOOKUP.get(key[:-1])
    return None


_EN_LOOKUP = {_norm_en(k): v for k, v in _EN_ALIAS.items()}

# 反向：中文标签 -> 它的英文写法（用于「用过的标签」在英文论文里也能命中）
_ZH_TO_EN: dict = {}
for _en, _zh in _EN_ALIAS.items():
    _ZH_TO_EN.setdefault(_zh, []).append(_norm_en(_en))

_EN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']{1,24}")


def _en_tags(text: str) -> dict:
    """扫出正文里的英文术语并折成中文，返回 {中文标签: 次数}。

    ⚠️ 这里**故意不用「一条大正则」**：把 400 多条备选拼成一个 alternation 后，
    Python 在每个非字母数字位置都要把 400 多个分支挨个试一遍 —— 实测 60k 字的
    论文要 6 秒。改成「切词 + 查表」是线性复杂度，同样的论文降到百毫秒级。
    先试 3 词短语、再 2 词、最后 1 词，长的命中就不再试短的。

    ⚠️ tokenizer **故意不吃连字符**：`Ultralow-Crosstalk` 如果切成一个 token，
    `_norm_en` 会把它归一成 "ultralow crosstalk"，于是里面的 `crosstalk` 永远试不到
    （实测踩过）。切成 "Ultralow" + "Crosstalk" 两个相邻 token（间隔是 `-`，
    下面的 gap 允许它），span=1 就能命中 `crosstalk`。

    ⚠️ 短缩写（≤3 字符）额外要求**原文里带大写**。否则会把公式里的
    `ln(x)` 当成「铌酸锂」、`sin(θ)` 当成「氮化硅」—— 这两个是实测埋过的雷。
    论文写缩写本来就都是大写（LN / ITO / THz / SiN），所以这条不影响正常命中。
    """
    out: dict = {}
    ms = list(_EN_WORD_RE.finditer(text))
    n = len(ms)
    for i in range(n):
        raw_tok = ms[i].group(0)
        toks_low = raw_tok.lower()
        if len(toks_low) <= 3 and raw_tok.islower():
            continue                     # ln / sin / cos 这类公式里的函数名，直接跳过
        for span in (3, 2, 1):
            if i + span > n:
                continue
            # 相邻词之间只允许空格 / 连字符，避免把两句话首尾的词拼在一起
            gap_ok = True
            for k in range(span - 1):
                if text[ms[i + k].end(): ms[i + k + 1].start()].strip(" -") != "":
                    gap_ok = False
                    break
            if not gap_ok:
                continue
            key = _norm_en(" ".join(ms[i + k].group(0) for k in range(span)))
            zh = _alias_lookup(key)
            if zh:
                out[zh] = out.get(zh, 0) + 1
                break
    return out


_EN_ONE_RE: dict = {}


def _count_en(text: str, en: str) -> int:
    """数某个英文写法在正文里出现几次（带词边界，避免 tem 命中 system）。

    ⚠️ ≤3 字符的缩写要求**原文带大写**，和 `_en_tags` 保持一致：论文写缩写都是
    LN / ITO / SiN 这种，而公式里的 ln(x)、sin(θ) 是小写。不区分大小写会把它们
    当成铌酸锂、氮化硅 —— 实测一篇满是 ln(...) 的论文因此把「铌酸锂」推成了
    「用过」标签。
    """
    pat = _EN_ONE_RE.get(en)
    if pat is None:
        pat = re.compile(r"(?<![A-Za-z0-9])" + _en_pattern(en) + r"(?![A-Za-z0-9])", re.I)
        _EN_ONE_RE[en] = pat
    if len(en) <= 3:
        return sum(1 for m in pat.finditer(text) if not m.group(0).islower())
    return len(pat.findall(text))


# 词表里的中文词（长度 >= 2），直接拿去正文里数
_ZH_VOCAB = [t for t in _ZH_TERMS.split() if len(t) >= 2]

# 正文里有没有汉字 —— 英文论文是常态，没有就整段跳过中文那一套（省几百毫秒）
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# ---------------------------------------------------------------------------
# 分区分权：标题 ≫ 摘要 ≫ 正文（2026-10-14 换的新方法）
#
# 为什么必须这么做：整篇按词频统计噪声太大 —— 「刻蚀」「表征」「掺杂」这类工艺词
# 在方法一节反复出现，会盖过真正代表这篇论文的「铌酸锂」「串扰」「相移器」。
# 实测：「Femtojoule, femtosecond all-optical switching in **lithium niobate**
# nanophotonics」这篇，标题里的「铌酸锂」「飞秒」一个都进不了候选。
# 标题和摘要才是作者自己对主题的总结，权重必须高出一个量级。
#
# 另外**必须掐掉参考文献**：实测一篇铌酸锂论文会从参考文献里冒出「石墨烯」当标签。
# ---------------------------------------------------------------------------
_W_TITLE, _W_ABSTRACT, _W_BODY = 12, 6, 1
# 「用过」标签的支撑度门槛：标题/摘要里出现，或正文里至少出现这么多次。
# 实测一篇铌酸锂论文正文里 graphene 只出现 1 次，却会把「石墨烯」推成标签。
_KNOWN_MIN_BODY = 3
# 新候选的最低得分：正文里只冒过一次的碎片不推给用户（标题命中一次就是 12 分）
_MIN_SCORE = 2

# ---------------------------------------------------------------------------
# 跨论文词频（IDF）—— 解决「换哪篇论文，识别出来的标签都一样」
#
# 只按「这一篇里出现多少次」排序有个致命毛病：**领域通用词会霸榜**。
# 实测用户 11 篇论文：光开关出现在 9 篇、掺杂 8 篇、硅 8 篇、光谱/损耗/波导各 7 篇 ——
# 于是不管换哪篇，第一个标签几乎都是「光开关」，标签就失去了区分作用。
#
# 这里补上 TF-IDF 缺的那一半：**一个词在你整个库里出现过几篇，就按比例降权。**
#   · `_FIELD_DF` 是从用户真实论文库实测出来的词频（69 个词，语料 11 篇），
#     当初始语料。表里没有的词一律按「0 篇有它」算，也就是最区分性。
#   · 之后每识别一篇就往 `数据/tag_corpus.json` 里累加，语料越用越准。
# 它只会**降权**泛用词、不会凭空造词，所以对没见过的领域是安全的。
# ---------------------------------------------------------------------------
_FIELD_N = 11
_FIELD_DF = {
    "光开关": 9, "掺杂": 8, "硅": 8, "光谱": 7, "损耗": 7, "波导": 7,
    "带宽": 6, "折射率": 6, "调制器": 6, "偏振": 5, "消光比": 5, "相移器": 5,
    "等离激元": 5, "金属": 5, "介电常数": 4, "介质": 4, "刻蚀": 4, "开关时间": 4,
    "开关速度": 4, "插入损耗": 4, "氧化物": 4, "氧化铟锡": 4, "激光器": 4, "石墨烯": 4,
    "色散": 4, "表征": 4, "表面等离激元": 4, "谐振腔": 4, "透射率": 4, "光子集成芯片": 3,
    "光栅": 3, "全光": 3, "带隙": 3, "时域有限差分": 3, "电光": 3, "绝缘体上硅": 3,
    "良率": 3, "迁移率": 3, "非线性光学": 3, "代工": 2, "传感器": 2, "光电探测器": 2,
    "分束器": 2, "响应时间": 2, "太赫兹": 2, "干涉": 2, "干涉仪": 2, "开关能量": 2,
    "微机电系统": 2, "微腔": 2, "晶圆": 2, "晶格": 2, "氮化硅": 2, "热光": 2,
    "相变材料": 2, "硅基光子学": 2, "碳纳米管": 2, "纳秒": 2, "缺陷": 2, "群速度": 2,
    "能带": 2, "自由载流子": 2, "衍射": 2, "费米面": 2, "超表面": 2, "近零介电常数": 2,
    "铌酸锂": 2, "飞秒": 2, "马赫-曾德尔": 2,
}
_CORPUS: dict = {"loaded": False, "n": 0, "df": {}, "seen": []}
_CORPUS_SEEN_MAX = 500
_CORPUS_LOCK = threading.Lock()
_CORPUS_PATH: list = []          # 缓存 data_dir() 结果：它会建目录 + 写探针，别每次调


def _corpus_path() -> Path:
    if not _CORPUS_PATH:
        try:
            _CORPUS_PATH.append(data_dir() / "tag_corpus.json")
        except Exception:
            _CORPUS_PATH.append(Path("tag_corpus.json"))
    return _CORPUS_PATH[0]


def _corpus() -> dict:
    """读取累积语料（只读一次；文件坏了就当空的，不影响主流程）。"""
    if not _CORPUS["loaded"]:
        with _CORPUS_LOCK:
            if not _CORPUS["loaded"]:
                _CORPUS["loaded"] = True
                try:
                    p = _corpus_path()
                    if p.is_file():
                        j = json.loads(p.read_text(encoding="utf-8"))
                        _CORPUS["n"] = max(0, int(j.get("n", 0) or 0))
                        df = j.get("df")
                        if isinstance(df, dict):
                            _CORPUS["df"] = {str(k): int(v) for k, v in df.items()
                                             if isinstance(v, (int, float)) and int(v) > 0}
                        seen = j.get("seen")
                        if isinstance(seen, list):
                            _CORPUS["seen"] = [str(x) for x in seen][-_CORPUS_SEEN_MAX:]
                except Exception:
                    pass
    return _CORPUS


def _corpus_add(terms, paper_key: str) -> None:
    """把这篇论文的词记进语料 —— 下次识别别的论文时它们就算「见过」了。

    ⚠️ 按论文指纹去重：同一篇反复点「自动识别标签」不能重复计数，
    否则那篇的词会被自己刷成「泛用词」，越点越偏。
    ⚠️ 写文件用「先写临时文件再原子替换」：直接 write_text 写到一半被中断会留下
    半截 JSON，下次读取失败、整份语料就丢了。
    """
    with _CORPUS_LOCK:                 # 本机接口是多线程的，两次识别可能并发
        c = _corpus()
        if paper_key and paper_key in c["seen"]:
            return
        if paper_key:
            c["seen"].append(paper_key)
            if len(c["seen"]) > _CORPUS_SEEN_MAX:
                c["seen"] = c["seen"][-_CORPUS_SEEN_MAX:]
        c["n"] += 1
        for t in terms:
            c["df"][t] = c["df"].get(t, 0) + 1
        snapshot = {"n": c["n"], "df": dict(c["df"]), "seen": list(c["seen"])}
    try:
        p = _corpus_path()
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)             # 原子替换
    except Exception:
        pass


def _idf(term: str) -> float:
    """区分度系数：库里越多篇有这个词，分越低。

    df = 实测词频（按语料规模**等比放大**）+ 之后累积的；n = 语料篇数。
    ⚠️ 等比放大这一步不能省：实测词表的篇数（11）是固定的，而 n 会随用户识别
       新论文而增长 —— 不放大的话「光开关 9/11」会变成「9/31」，
       IDF 反而涨回去，又回到「每篇都推光开关」。放大后比例不变，惩罚才稳定。
    """
    c = _corpus()
    n = _FIELD_N + c["n"]
    df = _FIELD_DF.get(term, 0) * (n / _FIELD_N) + c["df"].get(term, 0)
    return math.log((n + 1) / (df + 1)) + 1.0


# 排序用的两个旋钮（网格搜索实测出来的，见交接文档）
_TF_SUBLINEAR = True     # 词频取 log1p 压一下
_IDF_POWER = 1.0         # IDF 次方（网格搜索实测：1.0 在「去重」和「支撑度」之间最好）
_KNOWN_BONUS = 1.25      # 「用过」的标签给一点加成（很小，压不过区分度）


# ---------------------------------------------------------------------------
# 通用语料「泛用词」惩罚表
#
# 解决什么：`_idf()` 只看**你自己的库**，它分不清「罕见」和「泛用」——
# 实测一份中文论文里，「超过」「表现」「发生」这些泛词因为不在领域词表里，
# IDF 拿满 2.95 分，反而把「光开关」（在你的库里 9/11 篇都有，IDF 被压到 1.03）
# 挤到第 42 名。真术语干不过连接词。
#
# 做法：引入 jieba 自带的通用语料 IDF（27 万词，来自人民日报等通用文本）。
# 保留 idf ≤ 7 的 2817 个词作为「泛用词」表 —— 它们在任何中文文本里都高频，
# 出现在论文里多半是连接词、章节名或碎片，不是你要的标签。
#
# 表以 base64(zlib) 内嵌（22 KB），避免依赖外部文件、也不用改打包配置。
# 真术语（太赫兹 / 超表面 / 相变材料…）**不在这张表里**，惩罚系数为 1.0，不受影响。
# ---------------------------------------------------------------------------
_BG_IDF_B64 = (
    "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"
    "6ySMSXJ2/P8A8sLmTA=="
)
_BG_IDF: dict | None = None


def _bg_idf() -> dict:
    """解出泛用词表 {词: 通用语料 idf}。第一次用时才解析，之后缓存。"""
    global _BG_IDF
    if _BG_IDF is None:
        try:
            import base64 as _b64
            import zlib as _zl
            raw = _zl.decompress(_b64.b64decode(_BG_IDF_B64)).decode("utf-8")
            d = {}
            for ln in raw.splitlines():
                i = ln.rfind(" ")
                if i > 0:
                    try:
                        d[ln[:i]] = float(ln[i + 1:])
                    except Exception:
                        pass
            _BG_IDF = d
        except Exception:
            _BG_IDF = {}
    return _BG_IDF


def _bg_penalty(term: str) -> float:
    """泛用词惩罚系数（0.15~1.0）。不在表里 = 真术语，返回 1.0 不惩罚。

    曲线用 1.5 次方：让 idf 偏低的词掉得更狠。
    实测「超过」(idf 4.54) → 系数 0.49，能把它的分砍掉一半，
    刚好压到真术语（12 分档）之下。
    """
    v = _bg_idf().get(term)
    if v is None:
        return 1.0
    return max(0.15, min(1.0, (v / 7.0) ** 1.5))


def _rank(term: str, cnt: int, vocab) -> float:
    """排序分 = 压过的词频 × 领域区分度 × 泛用词惩罚。

    · 词频取 log1p：原始词频动态范围太大（标题命中一次就 12 分、正文一次才 1 分），
      不压的话 IDF 那两三倍的惩罚根本压不住「光开关」这种霸榜词。
    · IDF 再取 `_IDF_POWER` 次方，让「整个库里到处都是」的词掉得更狠。
    · `_bg_penalty` 是**第二把尺子**：光看自己的库分不清「罕见」和「泛用」，
      拿通用语料再压一道，「超过 / 表现 / 发生」这类词就翻不了身。
    """
    base = cnt + (3 if term in vocab else 0)
    if _TF_SUBLINEAR:
        base = math.log1p(base)
    return base * (_idf(term) ** _IDF_POWER) * _bg_penalty(term)
_REF_HEAD_RE = re.compile(r"(?:^|\s)(?:references|bibliography|参考文献)\s*[:：]?\s*(?![a-z])", re.I)
_NUMREF_RE = re.compile(r"\[\s*1\s*\]")
_ABS_RE = re.compile(
    r"\babstract\b\s*[:：]?\s*(.{80,4000}?)"
    r"(?=\bkeywords?\b|\bindex terms\b|\bintroduction\b|\b1\s*[\.、]\s)", re.I | re.S)
_KW_RE = re.compile(r"\b(?:keywords?|index terms)\b\s*[:：]?\s*(.{5,300})", re.I | re.S)


def _ref_cut(t: str):
    """参考文献从哪儿开始（返回偏移，找不到返回 None）。

    ⚠️ 实测：arXiv 那几篇的正文文本里**根本没有 "References" 这个词** ——
    pypdf 把标题行整行漏掉了，只剩一条条 `[1] [2]` 的条目（结尾能看见
    "[40] C. R. Phillips, …"）。所以不能只靠标题词，还得认「连续编号条目」这个形态：
    找最后一个满足「`[1]` 后面 4000 字内还跟着 `[2]` 和 `[3]`」的位置。
    """
    n = len(t)
    m = _REF_HEAD_RE.search(t)
    if m and m.start() > n * 0.45:
        return m.start()
    last = None
    for m in _NUMREF_RE.finditer(t):
        if m.start() < n * 0.45:
            continue
        tail = t[m.start(): m.start() + 4000]
        if re.search(r"\[\s*2\s*\]", tail) and re.search(r"\[\s*3\s*\]", tail):
            last = m.start()
    return last


# 「作者 / 单位 / 投稿信息」块的特征行 —— 兜底找摘要时要跳过它们
_META_LINE_RE = re.compile(
    r"@|"
    r"\b(?:Universit(?:y|ies|e|at)|Institut(?:e|o)|Department|Faculty|Academy"
    r"|College|Laborator(?:y|ies)|School of|Centres? for|Key Laboratory)\b|"
    r"\b\d{5,6}\b|"
    r"\b(?:Received|revised|accepted|published|Dated|Doc\. ID"
    r"|contributed equally|Corresponding author)\b",
    re.I)


def _fallback_abstract(t: str) -> str:
    """抓不到 "Abstract" 这个词时的退路。

    ⚠️ 不能直接取 `t[400:1800]`。实测 9 篇真实论文里有 2 篇（arXiv-1905.02315、
    arXiv-2107.09906）pypdf 把 **"Abstract" 那一行整行漏掉**，于是兜底窗口正好落在
    作者 / 单位行上 —— 抓回来的是
    `'t-sen University, Guangzhou 510000 , China 2 South China Academy of …'`。
    后果有两层：① 摘要本该拿 ×6 权重，结果喂给了机构名和作者名；
    ② 这些词随后进了标签与语料（`数据/tag_corpus.json` 里真出现过「北京理工大学」）。

    改法：先认出「作者 + 单位 + 投稿信息」那一块，跳到它之后，再取一段当摘要。
    认不出来（结构不像论文首页）就保持原来的行为，宁可不变也不要变得更差。
    """
    head = t[:1200]
    last = None
    for m in _META_LINE_RE.finditer(head):
        last = m.end()
    if last is None:
        return t[400:1800]
    pos = last
    for _ in range(6):                       # 最多再跳过 6 行同类元数据
        nl = t.find("\n", pos)
        if nl < 0:
            break
        nxt = nl + 1
        line = t[nxt:].split("\n", 1)[0]
        if len(t) - nxt > 300 and _META_LINE_RE.search(line):
            pos = nxt                        # 这一行还是作者 / 单位信息，继续往下
            continue
        pos = nxt
        break
    seg = t[pos:pos + 1400]
    # 跳过头了（剩下的正文本就不长）就退回原行为，别把摘要切成空段
    return seg if len(re.sub(r"\s+", "", seg)) >= 120 else t[400:1800]


def _split_zones(text: str):
    """切成 (标题区, 摘要区, 正文) —— 参考文献已掐掉。"""
    t = text
    cut = _ref_cut(t)
    if cut:
        t = t[:cut]
    title = t[:400]
    abstract = ""
    m = _ABS_RE.search(t)
    if m:
        abstract = m.group(1)
    k = _KW_RE.search(t)
    if k:
        abstract += " " + k.group(1)
    if not abstract:
        # ⚠️ 兜底：跟 "References" 一样，"Abstract" 这个标题词也常被 pypdf 整行漏掉。
        #    但「标题之后那一段」并不等于摘要 —— 中间可能整段都是作者和单位
        #    （见 _fallback_abstract 的说明），所以必须先把那一块跳过去。
        abstract = _fallback_abstract(t)
    return title, abstract, t


def _zh_min_for(weight: int) -> int:
    """标题 / 摘要区很短，门槛必须低，否则「飞秒」这种只出现一次的词全被滤掉。"""
    return 1 if weight > 1 else 3


# ---------------------------------------------------------------------------
# 人名过滤
#
# 为什么必须有这道：`_split_zones` 把开头 400 字当「标题区」，而**作者行就在里面**
# —— 作者名于是吃到 ×12 的标题权重，直接把「刘芯宇」「孙甜甜」「霍燕燕」顶成标签。
# 实测语料文件里真的混进了 5 个作者名。
#
# 判定故意做得很保守（四个条件同时满足才丢）：
#   ① 长度 2~3（中文姓名的长度）
#   ② 首字在一个**收窄过的**姓氏表里 —— 像「高 石 金 白 周 张 林 江 田 龙 马」
#      这些既是姓、又是大量科技词的开头（高频 / 石墨 / 金属 / 周期 / 张力…），
#      收窄掉才不会误杀真词；
#   ③ 不在科研词表里（词表命中说明是真术语，放行）；
#   ④ **只出现在标题区**，摘要和正文里一次都没有 —— 真术语很少这么「只在开头露一面」。
# ---------------------------------------------------------------------------
_CJK_CHARS = re.compile(r"[\u4e00-\u9fff]")
# 收窄过的中文姓氏：剔除「高石金白周张林江田龙马黄曹成石」这类会跟科技词撞车的字
_SURNAMES = set(
    "赵钱孙李郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施"
    "孔严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌"
    "苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安"
    "常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛"
    "禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席"
    "季麻强贾路娄危盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝"
    "管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄麴家封芮羿储靳汲邴糜松井段富"
    "巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭"
    "历戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索"
    "咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉"
    "宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充"
    "慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文"
    "寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简"
    "饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
# 这些字当姓氏时很常见，但当科技词开头更常见 —— 从姓氏表里剔除，宁漏勿错杀
# ⚠️ 方向别搞反：这里是「**要剔除**的姓氏」—— 那些「是姓、但更是科技词开头」的字。
#    最开始我把「王李刘陈孙」这些**最常见**的姓写进了这里，方向反了，
#    结果「刘芯宇」「孙甜甜」根本拦不住。
#    现在只保留实测会跟科技词撞车的：高(高频) 石(石墨) 金(金属) 白(白光) 周(周期)
#    张(张力) 林 江 田 马 黄(黄光) + 储(储能) 元(元件) 全(全息) 关(开关) 单(单元)
#    双(双折射) 干(干涉) 应(应变) 皮(皮秒) 相(相变) 空(空位) 能(能带) 薄(薄膜)
#    解(解调) 费(费米) 鲁(鲁棒)
_SURNAME_TECH_COLLIDE = set("高石金白周张林江田马黄储元全关单双干应皮相空能薄解费鲁")

# 双重保护：① 显式列出会撞车的姓氏；② 再自动减去科研词表里**所有词的首字** ——
# 手写列表必然漏，数据驱动才不会漏。词表里有的词首字，一律不当姓氏看。
_SURNAMES -= _SURNAME_TECH_COLLIDE
# ⚠️ 只认长度 2~3 的词表项 —— 过滤器本身只管 2~3 字，
#    「霍尔效应」（4 字）不该把「霍」这个姓剔掉，否则「霍燕燕」就漏网了。
_SURNAMES -= {w[0] for w in _ZH_VOCAB if 2 <= len(w) <= 3}


def _looks_like_name(term: str, in_vocab: bool) -> bool:
    """像中文姓名吗 —— 只是「像」，真正的取舍还要看它出现在哪些区（见调用处）。"""
    if in_vocab:
        return False                       # 科研词表命中，是真术语
    if not (2 <= len(term) <= 3):
        return False
    if term in _TAG_STOP:
        return False
    if not all(_CJK_CHARS.match(ch) for ch in term):
        return False
    return term[0] in _SURNAMES


def _score_zone(text: str, weight: int, counts: dict, vocab: set,
                zones: dict | None = None, zone: str = "") -> None:
    """把一段文本里的候选词按 weight 累加进 counts。

    `zones` 记录每个词**出现在哪些区** —— 人名过滤靠它：作者名只在标题区露一面，
    摘要和正文里都不会再出现。
    """
    if not text:
        return
    # ⚠️ _en_tags 是这一段的性能大头，**只算一次**再复用（以前 zones 那一遍和
    #    下面 ① 那一遍各调了一次，同一段文本白跑两遍）。
    en = _en_tags(text)
    if zones is not None and zone:
        for zh in en:
            zones.setdefault(zh, set()).add(zone)
        for term in _ZH_VOCAB:
            if term in text:
                zones.setdefault(term, set()).add(zone)
    # ① 英文术语 → 中文（切词查表，线性复杂度）
    for zh, c in en.items():
        counts[zh] = counts.get(zh, 0) + c * weight
        vocab.add(zh)
    # ② 科研词表里的中文词直接数（jieba 缺席时这条尤其顶用）
    #    ⚠️ 也要过停用词表：词表本身不干净（「堆叠」这种泛用词就在里面）
    for term in _ZH_VOCAB:
        if term in _TAG_STOP:
            continue
        c = text.count(term)
        if c:
            counts[term] = counts.get(term, 0) + c * weight
            vocab.add(term)
    # ③ 中文分词候选（jieba 优先，缺了退到 n-gram）
    if _CJK_RE.search(text):
        zmin = _zh_min_for(weight)
        got = _zh_terms(text, zmin)
        if got is None:
            got = _zh_by_ngram(text, zmin)
        for g, c in got:
            counts[g] = counts.get(g, 0) + c * weight
            if zones is not None and zone:
                zones.setdefault(g, set()).add(zone)


def _zh_terms(text: str, zh_min: int):
    """用 jieba 切词挑中文候选；jieba 不可用就返回 None（调用方退回 n-gram 法）。"""
    global _JIEBA_READY
    try:
        import jieba
        from collections import Counter
    except Exception:
        return None
    try:
        if not _JIEBA_READY:
            for w in _ZH_TERMS.split():
                try:
                    jieba.add_word(w, freq=(120000 if len(w) >= 3 else 20000))
                except Exception:
                    pass
            _JIEBA_READY = True
        cnt: Counter = Counter()
        for w in jieba.cut(text):
            w = w.strip()
            if len(w) < 2 or len(w) > 24 or w in _TAG_STOP:
                continue
            if all(ch in "0123456789%.-+,;:()[]" for ch in w):
                continue
            # jieba 会连英文字母一起切出来（实测冒出过 "pt"）。纯拉丁token交给
            # 上面英文那一遍处理（那边有长度和停用词过滤），这里只留带汉字的。
            if not any("\u4e00" <= ch <= "\u9fff" for ch in w):
                continue
            cnt[w] += 1
        return [(w, c) for w, c in cnt.most_common(400) if c >= zh_min]
    except Exception:
        return None


def _zh_by_ngram(text: str, zh_min: int):
    """没装 jieba 时的退路：切 2~5 字片段 + 成词性过滤。

    不如分词准（会切出「太赫兹超表」这种半截词），但至少能用。
    """
    import re
    runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    grams: dict = {}
    for run in runs:
        for L in (2, 3, 4, 5):
            for i in range(len(run) - L + 1):
                g = run[i:i + L]
                grams[g] = grams.get(g, 0) + 1
    cands = [g for g, c in grams.items() if c >= zh_min and g not in _TAG_STOP]
    cands.sort(key=lambda g: (-grams[g], -len(g)))
    cands = cands[:60]

    def _free_standing(g: str) -> bool:
        """左右邻都得够杂：只接同一个字的，多半是半截词。"""
        L, R = set(), set()
        for run in runs:
            start = 0
            while True:
                i = run.find(g, start)
                if i < 0:
                    break
                if i > 0:
                    L.add(run[i - 1])
                j = i + len(g)
                if j < len(run):
                    R.add(run[j])
                if len(L) > 3 and len(R) > 3:
                    return True
                start = i + 1
        return len(L) >= 2 and len(R) >= 2

    out: list = []
    for g in cands:
        if not _free_standing(g):
            continue
        if any((g in a) and grams.get(a, 0) >= grams[g] * 0.8 for a, _c in out):
            continue
        out.append((g, grams[g]))
        if len(out) >= 200:
            break
    return out


def _pdf_text_pypdf(raw: bytes, limit: int) -> str:
    """用 pypdf 抽 PDF 文字。"""
    out: list[str] = []
    got = 0
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(raw))
        for page in reader.pages[:60]:
            try:
                chunk = page.extract_text() or ""
            except Exception:
                continue
            out.append(chunk)
            got += len(chunk)
            if got >= limit:          # 够了就别再往下抽 —— 长论文能省一大截
                break
    except Exception:
        pass
    return " ".join(out)


def _pdf_text_pdfium(raw: bytes, limit: int) -> str:
    """用 PDFium 抽 PDF 文字（复用 `_pdf_doc` 的缓存）。"""
    out: list[str] = []
    got = 0
    try:
        doc = _pdf_doc(raw)
        for i in range(min(len(doc), 60)):
            try:
                chunk = doc[i].get_textpage().get_text_range() or ""
            except Exception:
                continue
            out.append(chunk)
            got += len(chunk)
            if got >= limit:
                break
    except Exception:
        pass
    return " ".join(out)


def _text_of(raw: bytes, kind: str, limit: int = 260_000) -> str:
    """把 PDF / Word / PPT 里的文字抠出来（截断到 limit 字符，够用就行）。"""
    kind = (kind or "").lower()
    out: list[str] = []
    if kind == "pdf":
        # ⚠️ 两道抽取器，取更长的那个。pypdf 对残缺 / 非标准 PDF 很挑 —— 实测一份
        #    下载不完整的 PDF 直接抛 "Stream has ended unexpectedly"，抽出 0 字，
        #    于是「自动识别标签」悄悄什么都不给，用户只看到「不行」。
        #    PDFium 是 Chrome 用的那个引擎，对现实里的畸形 PDF 宽容得多；
        #    反过来也有 pypdf 能读而 PDFium 读不了的，所以两个都试。
        best = _pdf_text_pypdf(raw, limit)
        if len(best) < 400:
            alt = _pdf_text_pdfium(raw, limit)
            if len(alt) > len(best):
                best = alt
        out.append(best)
    elif kind in ("docx", "pptx"):
        import re as _re
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names = z.namelist()
                if kind == "docx":
                    names = [n for n in names if n == "word/document.xml"]
                else:
                    names = [n for n in names
                             if _re.match(r"ppt/slides/slide\d+\.xml$", n)]
                for n in names[:120]:
                    try:
                        xml = z.read(n).decode("utf-8", "ignore")
                    except Exception:
                        continue
                    # 标签之间的才是正文，其余去掉。
                    # ⚠️ 别给标签长度设上限：<w:document> 上挂着一长串 xmlns 声明，
                    #    长度限制会让它匹配不上，命名空间字符串就漏进正文了。
                    out.append(_re.sub(r"<[^>]*>", " ", xml))
        except Exception:
            pass
    joined = " ".join(out)
    # ⚠️ 折叠空格 / 制表符（保留换行，跨行断词还要用）。
    #    Word / PPT 的 XML 里全是缩进 —— 不折叠的话实测一份 PPT 抽出来是
    #    ' \n        组会        '，48 个字符里大半是空白：① 「抽不出文字」的
    #    长度判断被灌水骗过；② 标题区（前 400 字）可能整段都是空格，×12 权重白给。
    joined = re.sub(r"[ \t\u00a0\u3000]+", " ", joined)
    return joined[:limit].translate(_LIGATURES)


def _overlap(a: str, b: str) -> float:
    """两个字面标签的重合度（0~1）。

    按**较短那个**的「不同字符被覆盖的比例」算 —— 这样「开关」对「光开关」是 1.0
    （完全重复），而「超表面」对「激光器」是 0（互不相干）。
    没有语义模型可用时的近似做法：中文术语的字面重合已经是很好的冗余信号。
    """
    if not a or not b:
        return 0.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    chars = set(short)
    if not chars:
        return 0.0
    return sum(1 for ch in chars if ch in long_) / len(chars)


def _tag_candidates(text: str, known: list, top: int = 8) -> list:
    """给出候选标签，形如 [{"tag": "...", "known": True/False}]。

    **只出中文**：英文术语先折成中文（见 `_EN_ALIAS`），折不到的直接丢掉。
    排序靠「分区分权」：标题 ×12、摘要 ×6、正文 ×1（见 `_split_zones`），
    词表 / 别名命中的再加 3 —— 让「铌酸锂」「串扰」这类专业词压过泛用词。
    """
    # 合并跨行断词（PDF 里 effi-\nciency 很常见），否则会冒出 ciency 这种碎片
    text = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", text)

    title, abstract, body = _split_zones(text)
    counts: dict = {}          # 中文标签 -> 加权得分
    vocab: set = set()         # 来自科研词表 / 英文别名的（高置信）
    zones: dict = {}           # 标签 -> 出现在哪些区（"t" 标题 / "a" 摘要 / "b" 正文）
    _score_zone(title, _W_TITLE, counts, vocab, zones, "t")
    _score_zone(abstract, _W_ABSTRACT, counts, vocab, zones, "a")
    _score_zone(body, _W_BODY, counts, vocab, zones, "b")

    # 用户以前用过的标签：同样分区分权；英文别名也算 —— 英文论文里中文标签本来
    # 不会出现，不折一下「用过」这条路径就永远是空的
    # 所有候选（**含「用过」的**）算同一个分，再统一排序。
    # ⚠️ 不能让「用过」无条件霸榜：用户库里 9/11 篇都标了「光开关」，
    #    它一进 known 就永远排第一 —— 用户看到的就是「换哪篇论文标签都一样」。
    scored: dict = {k: _rank(k, c, vocab) for k, c in counts.items()}
    known_set: set = set()
    for t in known:
        t = str(t).strip()
        if not (1 < len(t) <= 24) or t in _TAG_STOP:
            continue
        ens = _ZH_TO_EN.get(t, ())

        def _cnt(z, _t=t, _ens=ens):
            c = z.count(_t)
            for _en in _ens:
                c += _count_en(z, _en)
            return c

        tc, ac, bc = _cnt(title), _cnt(abstract), _cnt(body)
        # ⚠️ 支撑度门槛：只在正文里偶然冒一两次的词不算「用过」——
        #    实测一篇铌酸锂论文会因为正文出现过 1 次 graphene 就把「石墨烯」推出来。
        if tc + ac == 0 and bc < _KNOWN_MIN_BODY:
            continue
        known_set.add(t)
        cnt = tc * _W_TITLE + ac * _W_ABSTRACT + bc * _W_BODY
        # 用过的词给一点加成（用户的标签体系该被尊重），但幅度很小 ——
        # 压不过「区分度」，否则又回到「每次都是光开关」。
        scored[t] = _rank(t, cnt, ()) * _KNOWN_BONUS

    # 去碎片：短的若被另一个候选整个包含、且长的得分不低太多，就只留长的。
    # 例：「相变」 vs 「相变材料」→ 只留「相变材料」；但「钙钛矿」若远比
    # 「钙钛矿太阳能电池」高频，则两个都留（阈值 0.5，避免误杀独立概念）。
    ordered = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    items: list = []
    picked: list = []                    # 已选中的标签，用于多样性去重
    dropped: set = set()                 # 被判定为人名而丢弃的
    for k, _s in ordered:
        if len(items) >= top:
            break
        if k not in known_set and counts.get(k, 0) < _MIN_SCORE:
            continue                     # 只冒过一次的碎片，别推给用户
        # 人名过滤：只在标题区露过一面的短词（作者行就在标题区里）
        if (k not in known_set and zones.get(k, set()) == {"t"}
                and _looks_like_name(k, k in vocab)):
            dropped.add(k)
            continue
        if any(k != a and k in a and scored.get(a, 0) >= scored[k] * 0.5
               for a, _sa in ordered):
            continue                     # 被更长的候选整个包含
        # 多样性（MMR 思路）：跟已选标签**字面重合度高**的跳过 ——
        # 「开关」和「光开关」、「调制」和「调制深度」这类近义重复只会把 Top-N 塞满，
        # 用户看不到别的方向。
        if any(_overlap(k, a) >= 0.6 for a in picked):
            continue
        picked.append(k)
        items.append({"tag": k, "known": k in known_set})
    # 把这篇的词记进语料 —— 下次识别别的论文时它们就算「见过」了
    # ⚠️ 一定要先去重：同一个词可能既在 counts 里、又在 known_set 里，
    #    重复传进去会让它在一篇论文里被算两次，把语料带偏。
    # ⚠️ 人名不能进语料 —— 进去了会污染 IDF，让真词被当成「到处都是」而降权。
    _corpus_add(sorted((set(t for t, c in counts.items() if c >= _MIN_SCORE)
                        | known_set) - dropped),
                hashlib.md5(text.encode("utf-8", "ignore")).hexdigest())
    return items[:top]


class Api:
    """暴露给页面 JS 的本机能力：把 IndexedDB 里的文件落地，并交给系统程序。

    ⚠️ 实例属性一律带下划线前缀（`_window` / `_tmp`），方法名 `_bind` 也是。
    原因：pywebview 的 `util.get_functions()` 会**递归遍历 js_api 对象上所有非可调用属性**
    来生成 JS 桥（`for name in dir(obj)`），只有 `_` 开头的会被跳过。
    一旦把 pywebview 的 Window 对象挂在 `self.window` 上，它就会顺着
    `window.native.*` 走进 WinForms/WebView2 控件的属性图 —— 每次属性访问都要跨 CLR 边界、
    部分还要求 UI 线程，直接把消息泵拖住，**表现就是启动时窗口「未响应」**，
    并在 stderr 刷出上百行 `Error while processing window.native.…`。
    """

    def __init__(self) -> None:
        self._window = None
        self._tmp = Path(tempfile.gettempdir()) / (APP_NAME + "_打开")
        try:
            self._tmp.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._tmp = Path(tempfile.gettempdir())

    def _bind(self, window) -> None:
        self._window = window

    def _write(self, name: str, data_b64: str) -> Path:
        raw = base64.b64decode(data_b64)
        safe = _safe_name(name)
        p = self._tmp / safe
        try:
            p.write_bytes(raw)
        except PermissionError:
            # 原文件正被 Office / WPS 占着，换个带序号的名字再写
            p = self._tmp / ("%d_%s" % (int(time.time()), safe))
            p.write_bytes(raw)
        return p

    def open_file(self, name: str, data_b64: str) -> str:
        """落地到临时目录，用系统默认程序打开。返回 'ok' 或 'err:...'。"""
        try:
            p = self._write(name, data_b64)
            os.startfile(str(p))          # Windows 专用
            return "ok"
        except Exception as e:
            return "err:" + str(e)

    def save_file(self, name: str, data_b64: str) -> str:
        """弹「另存为」对话框，写到用户选定的位置。"""
        try:
            if self._window is None:
                return "err:no-window"
            dest = self._window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=_safe_name(name))
            if not dest:
                return "cancelled"
            if isinstance(dest, (list, tuple)):
                dest = dest[0]
            Path(dest).write_bytes(base64.b64decode(data_b64))
            return "ok"
        except Exception as e:
            return "err:" + str(e)

    # ---- 内置幻灯片编辑器 ----
    def editor_base(self) -> str:
        """页面用它拿到编辑器的本地地址；资源缺失时返回 err: 开头。"""
        try:
            url = _editor_serve()
            return url if url else "err:编辑器资源缺失"
        except Exception as e:
            return "err:" + str(e)

    # ---- 应用内改 PPT 文字 ----
    def pptx_read(self, data_b64: str) -> str:
        """列出每页每个文本框的文字**与位置**。

        位置（EMU）用于在幻灯片上叠一层可编辑框，做到「像 Office 那样直接点文字改」。
        没有位置的纯文本列表做不到这一点。
        """
        try:
            from pptx import Presentation
        except Exception as e:
            return json.dumps({"error": "缺少 python-pptx：%s" % e})

        def _i(v) -> int:
            try:
                return int(v)
            except Exception:
                return 0

        def _marg(v, default: int) -> int:
            """内边距：**没设**才用默认值。

            ⚠️ 不能用 `_i(v) or default` —— 显式设成 0 是合法值（贴边排版很常见），
            被 `or` 吞掉后叠加层的左/上内边距会变成 0.1"/0.05"，文字位置跟着偏。
            """
            return default if v is None else _i(v)

        # PP_ALIGN: 1=LEFT 2=CENTER 3=RIGHT 4=JUSTIFY
        _AL = {1: "l", 2: "c", 3: "r", 4: "j"}
        # MSO_ANCHOR: 1=TOP 2=MIDDLE 3=BOTTOM
        _VA = {1: "t", 2: "m", 3: "b"}

        def _ph_font(tf) -> float | None:
            """从一个 text_frame 里挖出字号：先看 run，再看段落。"""
            try:
                for p in tf.paragraphs:
                    for r in p.runs:
                        if r.font.size is not None:
                            return float(r.font.size.pt)
                    if p.font.size is not None:
                        return float(p.font.size.pt)
            except Exception:
                pass
            return None

        def _inherited_font(slide, sh, level: int = 0) -> float | None:
            """占位符常常不写字号 —— 真实值在版式、母版占位符，或母版 txStyles 里。

            不查这几层，标题在编辑框里会缩成 12px、正文会撑到 32pt，
            底下的原文直接透出来。
            """
            layout = getattr(slide, "slide_layout", None)
            master = getattr(layout, "slide_master", None) if layout else None

            # 1) 版式 / 母版上同名占位符的显式字号
            try:
                idx = sh.placeholder_format.idx
            except Exception:
                idx = None
            if idx is not None:
                for src in (layout, master):
                    if src is None:
                        continue
                    try:
                        for ph in src.placeholders:
                            if ph.placeholder_format.idx != idx:
                                continue
                            got = _ph_font(ph.text_frame)
                            if got:
                                return got
                    except Exception:
                        pass

            # 2) 母版 XML 的 <p:txStyles>：PowerPoint 默认模板把字号全放这儿，
            #    python-pptx 没有对应 API，只能自己读 XML。
            #    sz 的单位是 1/100 磅。
            if master is not None:
                try:
                    from lxml import etree
                    ns = {
                        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                    }
                    el = master.element
                    tag = "titleStyle" if idx == 0 else "bodyStyle"
                    lv = min(max(level, 0) + 1, 9)
                    node = el.find(
                        ".//p:txStyles/p:%s/a:lvl%dpPr/a:defRPr" % (tag, lv), ns)
                    if node is not None and node.get("sz"):
                        return int(node.get("sz")) / 100.0
                    # 该级别没写就退回第 1 级
                    node = el.find(
                        ".//p:txStyles/p:%s/a:lvl1pPr/a:defRPr" % tag, ns)
                    if node is not None and node.get("sz"):
                        return int(node.get("sz")) / 100.0
                except Exception:
                    pass
            return None

        def _inherited_align(slide, sh):
            """对齐 / 垂直锚点也常常只写在版式或母版上。"""
            try:
                idx = sh.placeholder_format.idx
            except Exception:
                return None, None
            layout = getattr(slide, "slide_layout", None)
            master = getattr(layout, "slide_master", None) if layout else None
            for src in (layout, master):
                if src is None:
                    continue
                try:
                    for ph in src.placeholders:
                        if ph.placeholder_format.idx != idx:
                            continue
                        a = v = None
                        try:
                            tf = ph.text_frame
                            if tf.paragraphs and tf.paragraphs[0].alignment is not None:
                                a = _AL.get(int(tf.paragraphs[0].alignment))
                            if tf.vertical_anchor is not None:
                                v = _VA.get(int(tf.vertical_anchor))
                        except Exception:
                            pass
                        if a or v:
                            return a, v
                except Exception:
                    pass
            return None, None

        def _tx_align(slide, sh, level: int = 0):
            """母版 txStyles 的 algn —— PowerPoint 默认模板的「标题居中」就写在这儿。"""
            try:
                idx = sh.placeholder_format.idx
            except Exception:
                return None
            layout = getattr(slide, "slide_layout", None)
            master = getattr(layout, "slide_master", None) if layout else None
            if master is None:
                return None
            try:
                ns = {
                    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                }
                tag = "titleStyle" if idx == 0 else "bodyStyle"
                lv = min(max(level, 0) + 1, 9)
                node = master.element.find(
                    ".//p:txStyles/p:%s/a:lvl%dpPr" % (tag, lv), ns)
                if node is None:
                    node = master.element.find(
                        ".//p:txStyles/p:%s/a:lvl1pPr" % tag, ns)
                if node is not None:
                    return {"ctr": "c", "r": "r", "just": "j",
                            "l": "l", "dist": "j", "thaiDist": "j"}.get(node.get("algn"))
            except Exception:
                pass
            return None

        try:
            prs = Presentation(io.BytesIO(base64.b64decode(data_b64)))
            slides = []
            for i, slide in enumerate(prs.slides):
                shapes = []
                for j, sh in enumerate(slide.shapes):
                    # --- 图片：单独收一类，前端要能点选 + 换图 ---
                    if int(getattr(sh, "shape_type", -1) or -1) == 13:   # PICTURE
                        shapes.append({
                            "j": j, "kind": "pic",
                            "name": sh.name or ("图片 %d" % j),
                            "x": _i(sh.left), "y": _i(sh.top),
                            "w": _i(sh.width), "h": _i(sh.height),
                            "rot": float(getattr(sh, "rotation", 0) or 0),
                        })
                        continue
                    if not getattr(sh, "has_text_frame", False):
                        continue
                    tf = sh.text_frame
                    text = "\n".join(p.text for p in tf.paragraphs)
                    if not text.strip():
                        continue

                    # 字号：run -> 段落 -> 版式/母版 -> txStyles -> 按框高估算
                    lvl0 = 0
                    try:
                        lvl0 = int(tf.paragraphs[0].level or 0)
                    except Exception:
                        pass
                    fs = _ph_font(tf)
                    if fs is None:
                        fs = _inherited_font(slide, sh, lvl0)
                    if fs is None:
                        nl = max(1, len(text.split("\n")))
                        est = (_i(sh.height) / (nl * 1.35)) / 12700.0
                        fs = max(10.0, min(32.0, est))

                    # 对齐 / 垂直锚点
                    al = None
                    try:
                        if tf.paragraphs and tf.paragraphs[0].alignment is not None:
                            al = _AL.get(int(tf.paragraphs[0].alignment))
                    except Exception:
                        pass
                    va = None
                    try:
                        if tf.vertical_anchor is not None:
                            va = _VA.get(int(tf.vertical_anchor))
                    except Exception:
                        pass
                    if al is None or va is None:
                        ial, iva = _inherited_align(slide, sh)
                        if al is None:
                            al = ial
                        if va is None:
                            va = iva
                    if al is None:
                        al = _tx_align(slide, sh, lvl0)

                    # 内边距（EMU），默认按 PowerPoint 的 0.1"/0.05"
                    ml = _marg(getattr(tf, "margin_left", None), 91440)
                    mr = _marg(getattr(tf, "margin_right", None), 91440)
                    mt = _marg(getattr(tf, "margin_top", None), 45720)
                    mb = _marg(getattr(tf, "margin_bottom", None), 45720)

                    # 加粗 / 斜体 / 颜色（取第一个 run），给格式工具条回显用
                    bd = it = None
                    col = None
                    try:
                        for p in tf.paragraphs:
                            for r in p.runs:
                                if bd is None:
                                    bd = bool(r.font.bold) if r.font.bold is not None else None
                                if it is None:
                                    it = bool(r.font.italic) if r.font.italic is not None else None
                                if col is None:
                                    try:
                                        rgb = r.font.color.rgb
                                        if rgb is not None:
                                            col = str(rgb)
                                    except Exception:
                                        pass
                            if bd is not None and it is not None and col is not None:
                                break
                    except Exception:
                        pass

                    shapes.append({
                        "j": j,
                        "kind": "txt",
                        "name": sh.name or ("形状 %d" % j),
                        "text": text,
                        "x": _i(sh.left), "y": _i(sh.top),
                        "w": _i(sh.width), "h": _i(sh.height),
                        "rot": float(getattr(sh, "rotation", 0) or 0),
                        "fs": fs, "al": al, "va": va,
                        "ml": ml, "mr": mr, "mt": mt, "mb": mb,
                        "b": bd, "i": it, "col": col,
                    })
                slides.append({"i": i, "shapes": shapes})

            return json.dumps({
                "slides": slides,
                "sw": _i(prs.slide_width),
                "sh": _i(prs.slide_height),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def pptx_write(self, data_b64: str, edits_json: str) -> str:
        """按 edits 改 pptx，返回改好的文件（base64）。

        每条形如（可组合）：
          {"slide":0, "shape":3, "set":{"text":"…","x":…,"y":…,"w":…,"h":…,
                                        "fs":24,"bold":true,"italic":false,
                                        "color":"FF0000","align":"c","z":"front"}}
          {"slide":0, "shape":5, "image":"<base64>"}     换图
          {"slide":0, "shape":4, "del": true}            删除
          {"slide":0, "add": {"x":…,"y":…,"w":…,"h":…,"text":"…"}}   新建文本框

        单位：x/y/w/h 是 EMU，fs 是磅，color 是 6 位十六进制。
        改文字时每个段落沿用第一个 run 的字体，段内混排格式会被抹平。
        换图会把新图转成原图格式再替换，避免动 [Content-Type]。
        """
        try:
            from pptx import Presentation
            from pptx.util import Emu, Pt
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN
        except Exception as e:
            return json.dumps({"error": "缺少 python-pptx：%s" % e})

        _ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER,
                  "r": PP_ALIGN.RIGHT, "j": PP_ALIGN.JUSTIFY}

        def _set_image(slide, sh, img_b64: str) -> None:
            """替换图片：blip 的 rId 指向的 image part 直接换 blob。"""
            rId = sh._element.blip_rId
            part = slide.part.related_part(rId)
            raw = base64.b64decode(img_b64)
            ctype = (getattr(part, "content_type", "") or "").lower()
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(raw))
                out = io.BytesIO()
                if "jpeg" in ctype or "jpg" in ctype:
                    im.convert("RGB").save(out, format="JPEG", quality=92)
                elif "gif" in ctype:
                    im.save(out, format="GIF")
                elif "bmp" in ctype:
                    im.save(out, format="BMP")
                else:                       # 默认 PNG，透明通道能保住
                    im.save(out, format="PNG")
                raw = out.getvalue()
            except Exception:
                pass                        # 没 PIL 就原样写
            part._blob = raw

        def _set_text(sh, text: str) -> None:
            lines = str(text).split("\n")
            tf = sh.text_frame
            while len(tf.paragraphs) < len(lines):
                tf.add_paragraph()
            for p in list(tf.paragraphs)[len(lines):]:
                p._p.getparent().remove(p._p)
            for p, line in zip(tf.paragraphs, lines):
                runs = list(p.runs)
                if runs:
                    runs[0].text = line
                    for r in runs[1:]:
                        r.text = ""
                else:
                    p.add_run().text = line

        def _each_run(sh):
            """遍历所有 run；没有 run 的段落补一个，保证样式能落到文字上。"""
            for p in sh.text_frame.paragraphs:
                if not p.runs:
                    p.add_run().text = p.text or ""
                for r in p.runs:
                    yield p, r

        def _apply_set(slide, sh, s: dict) -> None:
            if "text" in s:
                _set_text(sh, s["text"])
            for k, attr in (("x", "left"), ("y", "top"), ("w", "width"), ("h", "height")):
                if s.get(k) is not None:
                    setattr(sh, attr, Emu(int(s[k])))
            if s.get("rot") is not None:
                sh.rotation = float(s["rot"])

            if getattr(sh, "has_text_frame", False):
                if s.get("align") in _ALIGN:
                    for p in sh.text_frame.paragraphs:
                        p.alignment = _ALIGN[s["align"]]
                need_font = any(s.get(k) is not None for k in ("fs", "bold", "italic", "color"))
                if need_font:
                    for _p, r in _each_run(sh):
                        f = r.font
                        if s.get("fs") is not None:
                            f.size = Pt(float(s["fs"]))
                        if s.get("bold") is not None:
                            f.bold = bool(s["bold"])
                        if s.get("italic") is not None:
                            f.italic = bool(s["italic"])
                        if s.get("color"):
                            try:
                                f.color.rgb = RGBColor.from_string(
                                    str(s["color"]).lstrip("#").upper())
                            except Exception:
                                pass

            z = s.get("z")
            if z in ("front", "back"):
                el = sh._element
                tree = el.getparent()
                tree.remove(el)
                if z == "front":
                    tree.append(el)
                else:
                    # spTree 前两个是 nvGrpSpPr / grpSpPr，插在它们之后
                    kids = list(tree)
                    idx = 2 if len(kids) >= 2 else 0
                    tree.insert(idx, el)

        try:
            edits = json.loads(edits_json)
            prs = Presentation(io.BytesIO(base64.b64decode(data_b64)))
            by_slide: dict[int, list] = {}
            for e in edits:
                by_slide.setdefault(int(e["slide"]), []).append(e)

            for si, items in by_slide.items():
                slide = prs.slides[si]
                snapshot = list(slide.shapes)       # 先取快照：删除不会让别的引用失效
                for e in items:
                    if e.get("add") is not None:
                        a = e["add"]
                        box = slide.shapes.add_textbox(
                            Emu(int(a.get("x", 0))), Emu(int(a.get("y", 0))),
                            Emu(int(a.get("w", 3000000))), Emu(int(a.get("h", 800000))))
                        box.text_frame.text = str(a.get("text", ""))
                        continue

                    j = int(e["shape"])
                    if j < 0 or j >= len(snapshot):
                        continue
                    sh = snapshot[j]

                    if e.get("del"):
                        sh._element.getparent().remove(sh._element)
                        continue
                    if e.get("image") is not None:
                        _set_image(slide, sh, str(e["image"]))
                        continue
                    if e.get("set"):
                        _apply_set(slide, sh, e["set"])
                        continue
                    if e.get("text") is not None:       # 兼容旧格式
                        if getattr(sh, "has_text_frame", False):
                            _set_text(sh, str(e["text"]))

            buf = io.BytesIO()
            prs.save(buf)
            raw = buf.getvalue()
            return json.dumps({"b64": base64.b64encode(raw).decode("ascii"),
                               "size": len(raw)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ---- 新建组会时自动猜标签 ----
    def suggest_tags(self, paper_b64: str, paper_kind: str = "",
                     slides_b64: str = "", slides_kind: str = "",
                     known_json: str = "[]", names: str = "") -> str:
        """从论文 / PPT 里猜标签。known=True 的是用户以前用过的（优先）。

        names 传两边的文件名 —— 文件名本身就常常带着方向词，别浪费。
        """
        try:
            parts = []
            for b, k in ((paper_b64, paper_kind), (slides_b64, slides_kind)):
                if b:
                    parts.append(_text_of(base64.b64decode(b), k))
            # ⚠️ 文件名必须放**最后**：它只是辅助线索。放最前面会落进「标题区」
            #    拿到 ×12 权重（比正文还重）—— 实测一份叫「幻灯片.pptx」的文件
            #    直接把「幻灯片」顶成了一个标签。
            parts.append(names or "")
            text = " ".join(parts)
            # ⚠️ 抽不出文字时必须**说清楚**，不能静默返回空 —— 否则用户只看到
            #    「识别不了」，根本不知道是扫描件、文件坏了、还是功能坏了。
            #    长度按**去掉空白**之后算：光靠空白凑够 40 字符会让判断失效
            #    （实测一份只有两个字的 PPT 因为缩进空白而「过关」）。
            if len(re.sub(r"\s+", "", text)) < 40:
                return json.dumps(
                    {"ok": True, "items": [], "chars": len(text),
                     "reason": "这篇论文抽不出文字。多半是扫描件 / 图片型 PDF"
                               "（正文是图片不是文字），或者文件没下载完整。"},
                    ensure_ascii=False)
            try:
                known = json.loads(known_json or "[]")
            except Exception:
                known = []
            if not isinstance(known, list):
                known = []
            known = [str(x) for x in known if str(x).strip()][:200]
            items = _tag_candidates(text, known)
            if not items:
                return json.dumps(
                    {"ok": True, "items": [], "chars": len(text),
                     "reason": "抽到了 %d 字，但没匹配到已知的科研词 —— "
                               "这篇的方向大概不在内置词表里，直接手打吧。" % len(text)},
                    ensure_ascii=False)
            return json.dumps({"ok": True, "items": items, "chars": len(text)},
                              ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def paper_pages(self, data_b64: str, kind: str = "pdf", dpi: int = 44) -> str:
        """列出每一页的**小缩略图**（JPEG），供「按页框选」时挑页。

        故意用低 dpi：一页几十 KB，40 页也就 1 MB 上下，不会把桥堵住。
        真正要插入的那块由 `paper_page_crop` 单独高清渲染。
        """
        try:
            if (kind or "").lower() != "pdf":
                return json.dumps({"ok": True, "pages": [], "total": 0,
                                   "note": "只有 PDF 支持按页框选"}, ensure_ascii=False)
            doc = _pdf_doc(base64.b64decode(data_b64))
            n = min(len(doc), _MAX_PAGE_THUMBS)
            scale = max(0.1, float(dpi) / 72.0)
            pages = []
            for i in range(n):
                page = doc[i]
                pw, ph = page.get_size()
                im = page.render(scale=scale).to_pil()
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=78)
                im.close()
                pages.append({"i": i, "w": round(pw), "h": round(ph),
                              "b64": base64.b64encode(buf.getvalue()).decode("ascii")})
            return json.dumps({"ok": True, "pages": pages, "total": len(doc),
                               "shown": n}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def paper_page_crop(self, data_b64: str, kind: str = "pdf", page: int = 0,
                        x: float = 0.0, y: float = 0.0, w: float = 1.0, h: float = 1.0,
                        max_px: int = 1400, fmt: str = "jpeg") -> str:
        """把某一页的某个矩形区域渲染成图。

        x / y / w / h 都是**相对整页的比例**（0~1）—— 前端只要把框选结果除以
        显示尺寸就行，不必去猜 PDF 那套「原点在左下角」的坐标系。
        max_px 控制渲染上限（预览用小值、真正插入用大值）。
        """
        try:
            if (kind or "").lower() != "pdf":
                return json.dumps({"ok": False, "error": "只有 PDF 支持按页框选"},
                                  ensure_ascii=False)
            doc = _pdf_doc(base64.b64decode(data_b64))
            i = int(page)
            if i < 0 or i >= len(doc):
                return json.dumps({"ok": False, "error": "页码超出范围"}, ensure_ascii=False)
            pg = doc[i]
            pw, ph = pg.get_size()                       # 单位：PDF 点
            x = min(max(float(x), 0.0), 0.999)
            y = min(max(float(y), 0.0), 0.999)
            w = min(max(float(w), 0.01), 1.0 - x)
            h = min(max(float(h), 0.01), 1.0 - y)
            # 渲染倍率：整页长边不超过 max_px，但至少 1x、最多 6x
            scale = min(6.0, max(1.0, float(max_px) / max(pw, ph)))
            im = pg.render(scale=scale).to_pil()
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            W, H = im.size
            box = (max(0, int(x * W)), max(0, int(y * H)),
                   min(W, int(round((x + w) * W))), min(H, int(round((y + h) * H))))
            box = (box[0], box[1], max(box[0] + 1, box[2]), max(box[1] + 1, box[3]))
            crop = im.crop(box)
            im.close()
            buf = io.BytesIO()
            if (fmt or "").lower() == "png":
                crop.save(buf, "PNG", optimize=True)
            else:
                crop.convert("RGB").save(buf, "JPEG", quality=86)
            data = buf.getvalue()
            return json.dumps({"ok": True, "b64": base64.b64encode(data).decode("ascii"),
                               "w": crop.size[0], "h": crop.size[1], "size": len(data)},
                              ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    def pptx_add_image(self, data_b64: str, slide_idx: int, img_b64: str) -> str:
        """把一张图插到第 slide_idx 页，并把这一页**我们插过的**图重排成版。

        只重排打了 `_IMG_TAG` 标记的图，PPT 自带的图一个都不动。
        版式：1 张居中放大；2 张左右并排；3~4 张 2×2；再多走 3 列网格。
        （不重排的话，同一页插第二张会和第一张**完全重叠**，看着像没插进去。）
        """
        try:
            from pptx import Presentation
            prs = Presentation(io.BytesIO(base64.b64decode(data_b64)))
            slides = list(prs.slides)
            idx = int(slide_idx)
            if idx < 0 or idx >= len(slides):
                return json.dumps({"ok": False, "error": "页码超出范围"}, ensure_ascii=False)
            img_bytes = base64.b64decode(img_b64)
            slide = slides[idx]
            sw, sh = prs.slide_width, prs.slide_height
            pic = slide.shapes.add_picture(io.BytesIO(img_bytes), 0, 0)
            try:
                pic.name = _IMG_TAG
            except Exception:
                pass
            ours = [s for s in slide.shapes if s.shape_type == 13 and s.name == _IMG_TAG]
            n = max(1, len(ours))
            cols = 1 if n == 1 else (2 if n <= 4 else 3)
            rows = (n + cols - 1) // cols
            bx, by = int(sw * 0.06), int(sh * 0.24)      # 版心：上边让给标题
            bw, bh = int(sw * 0.88), int(sh * 0.70)
            cw, ch = max(1, bw // cols), max(1, bh // rows)
            pad = int(min(cw, ch) * 0.06)
            for i, s in enumerate(ours):
                r, c = divmod(i, cols)
                cell_w, cell_h = max(1, cw - 2 * pad), max(1, ch - 2 * pad)
                ratio = (s.width / s.height) if s.height else 1.0   # 只用比例，避免反复缩放累积
                if cell_w / cell_h > ratio:
                    h = cell_h; w = max(1, int(h * ratio))
                else:
                    w = cell_w; h = max(1, int(w / ratio))
                s.width, s.height = w, h
                s.left = bx + c * cw + pad + (cell_w - w) // 2
                s.top = by + r * ch + pad + (cell_h - h) // 2
            buf = io.BytesIO()
            prs.save(buf)
            raw = buf.getvalue()
            return json.dumps({"ok": True, "b64": base64.b64encode(raw).decode("ascii"),
                               "size": len(raw), "count": len(ours)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 本机接口：让「用浏览器打开的网页版」也能用上 exe 的能力
#
# 网页版自己没有 Python 后端，但 exe 开着的时候可以连它 —— 于是「编辑 / 插图 /
# 自动识别标签」在浏览器里也能用，跟 exe 里一样；exe 没开就退回基础功能。
#
# ⚠️ 安全上必须做三道，因为 127.0.0.1 上的接口本机任何页面都可能来敲：
#   ① 只在 127.0.0.1 监听，并且**只接受 Origin 为 null 的请求**（file:// 打开的
#      页面就是 null）。普通网站发来的请求一律 403 且**不带 CORS 头**，
#      浏览器读不到任何内容。实测已确认这条挡得住。
#   ② 只放行一份**方法白名单**：`save_file`（要用原生另存为对话框）不开放。
#   ③ `open_file` 会用系统程序打开文件，所以再加一道后缀白名单，挡住 .exe/.bat
#      这类可执行文件。
# ---------------------------------------------------------------------------
BRIDGE_PORTS = range(39177, 39187)
BRIDGE_APP_ID = "zuhui-workbench"
_BRIDGE_OPENABLE = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
                    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".txt", ".md", ".csv"}
_BRIDGE_ALLOW = {
    "editor_base", "suggest_tags",
    "paper_pages", "paper_page_crop",
    "pptx_add_image", "pptx_read", "pptx_write", "open_file",
}


def _make_bridge_handler(api):
    import http.server

    class BridgeHandler(http.server.BaseHTTPRequestHandler):
        server_version = "zuhui-bridge"
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _origin_ok(self) -> bool:
            o = self.headers.get("Origin")
            return o is None or o == "null"

        def _send(self, obj, code: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _reject(self) -> None:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_OPTIONS(self):
            if not self._origin_ok():
                return self._reject()
            self._send({"ok": True})

        def do_GET(self):
            if not self._origin_ok():
                return self._reject()
            if self.path.split("?")[0] == "/ping":
                return self._send({"ok": True, "app": BRIDGE_APP_ID, "ver": 1})
            self._send({"ok": False, "error": "不认识的路径"}, 404)

        def do_POST(self):
            if not self._origin_ok():
                return self._reject()
            if self.path.split("?")[0] != "/call":
                return self._send({"ok": False, "error": "不认识的路径"}, 404)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception as e:
                return self._send({"ok": False, "error": "请求解析失败：%s" % e})
            name = str(req.get("method") or "")
            args = req.get("args") or []
            if name not in _BRIDGE_ALLOW:
                return self._send({"ok": False,
                                   "error": "这个方法不开放给网页版：%s" % name})
            if name == "open_file":
                ext = Path(str(args[0]) if args else "").suffix.lower()
                if ext not in _BRIDGE_OPENABLE:
                    return self._send({"ok": False,
                                       "error": "网页版只能用系统程序打开文档和图片"})
            fn = getattr(api, name, None)
            if not callable(fn):
                return self._send({"ok": False, "error": "没有这个方法：%s" % name})
            try:
                return self._send({"ok": True, "result": fn(*args)})
            except Exception as e:
                return self._send({"ok": False, "error": str(e)})

    return BridgeHandler


def start_bridge() -> int | None:
    """起本机接口，返回端口号；起不来就返回 None（不影响 exe 本身）。"""
    import http.server
    try:
        handler = _make_bridge_handler(Api())
        for port in BRIDGE_PORTS:
            try:
                srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError:
                continue
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return port
    except Exception:
        pass
    return None


def selftest(window) -> None:
    """开窗后自检：确认页面加载、IndexedDB 可读写、背景层状态、本机桥可用。

    WebView2 首次启动 + file:// 下打开 IndexedDB 会比浏览器慢不少，这里给足 9 秒，
    否则会误判成「页面没渲染」。
    """
    time.sleep(9)
    try:
        _log("页面:", window.evaluate_js(
            "(function(){return JSON.stringify({"
            "title:document.title,"
            "canvas:getComputedStyle(document.getElementById('bg')).display,"
            "ui:!!document.querySelector('.empty,.row'),"
            "appLen:(document.getElementById('app')||{}).innerHTML?document.getElementById('app').innerHTML.length:0,"
            "bodyLen:document.body.innerHTML.length,"
            "ready:document.readyState,"
            "idb:typeof indexedDB!=='undefined',"
            "api:!!(window.pywebview&&window.pywebview.api&&window.pywebview.api.open_file)});})()"))
        window.evaluate_js("""
          window.__T = 'pending';
          try {
            var rq = indexedDB.open('selftest', 1);
            rq.onupgradeneeded = function () { rq.result.createObjectStore('s', { keyPath: 'k' }); };
            rq.onsuccess = function () {
              var db = rq.result;
              var tx = db.transaction('s', 'readwrite');
              tx.objectStore('s').put({ k: 'a', v: 'ok' });
              tx.oncomplete = function () {
                var g = db.transaction('s', 'readonly').objectStore('s').get('a');
                g.onsuccess = function () { window.__T = (g.result && g.result.v) || 'empty'; };
              };
            };
            rq.onerror = function () { window.__T = 'open-error'; };
          } catch (e) { window.__T = 'throw:' + e.message; }
        """)
    except Exception as e:
        _log("自检异常:", e)
    time.sleep(2.5)
    try:
        _log("IndexedDB 读写:", window.evaluate_js("window.__T"))
    except Exception as e:
        _log("读取失败:", e)
    window.destroy()


def main() -> int:
    # 调试用：命令行读一份 pptx 的文字，验证打包后的 python-pptx 可用
    if "--pptx-read" in sys.argv:
        i = sys.argv.index("--pptx-read")
        src = Path(sys.argv[i + 1])
        raw = base64.b64encode(src.read_bytes()).decode("ascii")
        print(Api().pptx_read(raw))
        return 0

    # 诊断用：检查打包进 exe 的编辑器能否被找出来并正常发出去（不需要窗口）
    if "--editor-check" in sys.argv:
        i = sys.argv.index("--editor-check")
        out = Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 else Path("editor-check.txt")
        rows = []
        try:
            root = _editor_root()
            rows.append("编辑器目录: %s" % (root or "（没找到）"))
            base = Api().editor_base()
            rows.append("服务地址  : %s" % base)
            if base.startswith("http"):
                with urllib.request.urlopen(base + "/lectern/index.html", timeout=8) as r:
                    body = r.read()
                    rows.append("index.html: %d 字节 / HTTP %s" % (len(body), r.status))
                with urllib.request.urlopen(base + "/_zuhui_embed.js", timeout=8) as r2:
                    rows.append("适配层    : %d 字节" % len(r2.read()))
                with urllib.request.urlopen(base + "/common/core.js", timeout=8) as r3:
                    rows.append("公共脚本  : %d 字节" % len(r3.read()))
        except Exception as e:
            rows.append("异常: %r" % (e,))
        try:
            out.write_text("\n".join(rows) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 0

    # 诊断用：命令行跑一次标签识别（验证打包后 jieba 词典还在、识别结果正常）
    if "--tag-check" in sys.argv:
        i = sys.argv.index("--tag-check")
        src = Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 else None
        out = Path(sys.argv[i + 2]) if len(sys.argv) > i + 2 else Path("tag-check.txt")
        rows = []
        try:
            import jieba
            rows.append("jieba      : %s" % getattr(jieba, "__version__", "?"))
        except Exception as e:
            rows.append("jieba      : 没有（%s）→ 会退到片段法" % e)
        if src and src.is_file():
            rawb = src.read_bytes()
            kind = src.suffix.lower().lstrip(".")
            text = _text_of(rawb, kind)
            rows.append("文件       : %s" % src.name)
            rows.append("抽出文字   : %d 字" % len(text))
            if text:
                _t, _a, _b = _split_zones(text)
                rows.append("标题区     : %s" % (" ".join(_t.split())[:70] or "（空）"))
                rows.append("摘要区     : %s" % (" ".join(_a.split())[:70] or "（空）"))
                _cut = _ref_cut(text)
                rows.append("参考文献   : %s" % (
                    "从第 %d 字截断（%d%%）" % (_cut, _cut * 100 // max(1, len(text)))
                    if _cut else "没找到，未截断"))
            res = json.loads(Api().suggest_tags(base64.b64encode(rawb).decode("ascii"),
                                                kind, "", "", "[]", src.name))
            if res.get("reason"):
                rows.append("说明       : %s" % res["reason"])
            rows.append("候选标签   : %s" % ("、".join(x["tag"] for x in res.get("items", []))
                                            or "（无）"))
        try:
            out.write_text("\n".join(rows) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 0

    # 诊断用：命令行验一次「按页渲染 + 框选」（确认打包后 pdfium 真的能用）
    if "--fig-check" in sys.argv:
        i = sys.argv.index("--fig-check")
        src = Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 else None
        out = Path(sys.argv[i + 2]) if len(sys.argv) > i + 2 else Path("fig-check.txt")
        rows = []
        try:
            import pypdfium2 as _pf      # noqa: F401
            rows.append("pypdfium2  : 已加载")
        except Exception as e:
            rows.append("pypdfium2  : 没有（%s）→ 按页框选不可用" % e)
        if src and src.is_file():
            raw = base64.b64encode(src.read_bytes()).decode("ascii")
            api = Api()
            r = json.loads(api.paper_pages(raw, src.suffix.lower().lstrip("."), 40))
            rows.append("文件       : %s" % src.name)
            if r.get("ok"):
                rows.append("页数       : %s" % r.get("total"))
                rows.append("缩略图     : %d 张（每张约 %.0f KB）"
                            % (len(r.get("pages", [])),
                               (len(r["pages"][0]["b64"]) / 1024) if r.get("pages") else 0))
            else:
                rows.append("页渲染失败 : %s" % r.get("error"))
            c = json.loads(api.paper_page_crop(raw, src.suffix.lower().lstrip("."),
                                               0, 0.0, 0.0, 1.0, 1.0, 800, "png"))
            rows.append("整页裁剪   : %s" % ("%dx%d, %d KB" % (c["w"], c["h"], c["size"] // 1024)
                                            if c.get("ok") else ("失败 " + str(c.get("error")))))
        try:
            out.write_text("\n".join(rows) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 0

    # 起本机接口 —— 用浏览器打开的网页版靠它拿到 exe 的能力（编辑/插图/识别标签）
    _bridge_port = start_bridge()

    html = find_html()
    if html is None:
        msg = ("找不到 %s。\n\n请把 %s 与 组会工作台.exe 放在同一个文件夹里。"
               % (HTML_NAME, HTML_NAME))
        try:
            webview.create_window(APP_NAME, html="<h1 style='font:16px sans-serif;padding:40px'>"
                                                 + msg.replace("\n", "<br>") + "</h1>")
            webview.start(gui="edgechromium")
        except Exception:
            _log(msg)
        return 2

    store = data_dir()
    icon = find_icon()
    api = Api()
    win_w, win_h = fit_window()

    window = webview.create_window(
        # 标题带上版本号：界面改动只有打包后才生效，出问题时要能一眼确认
        # 「你开的到底是哪一版」，否则容易在旧窗口上反复试（2026-10-17 踩过）。
        APP_NAME + " · " + BUILD_TAG,
        url=html.as_uri(),
        width=win_w, height=win_h,
        min_size=(960, 620),
        background_color="#f8f5fd",
        text_select=True,
        zoomable=True,
        confirm_close=False,
        js_api=api,
    )
    api._bind(window)

    kwargs = dict(gui="edgechromium", private_mode=False, storage_path=str(store))
    if icon:
        kwargs["icon"] = str(icon)

    if "--selftest" in sys.argv:
        log_path = app_dir() / "_selftest.log"
        try:
            log_path.unlink()
        except Exception:
            pass
        _log("HTML :", html)
        _log("数据 :", store)
        _log("图标 :", icon)
        webview.start(selftest, window, **kwargs)
    else:
        webview.start(**kwargs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
