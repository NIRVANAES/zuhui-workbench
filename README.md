# 组会工作台

本地优先的组会论文 / 幻灯片对照工作台。论文与 PPT 左右并排阅读、按页框选插图插进
PPT、离线识别论文标签，数据只存在本机，不上传任何服务器。

面向的场景：研究生组会。左手论文右手 PPT，讲到哪里对到哪里；看到好图当场裁下来插进
自己的幻灯片；一篇读完给它打几个标签，攒成自己的文献库。

## 功能

| 功能 | 说明 |
|---|---|
| 论文 / PPT 对照阅读 | 左右双栏，翻页联动，记录每篇的阅读进度（页码存本机） |
| 按页框选插图 | 把论文 PDF **整页渲染**后框选，所见即所得；直接抽内嵌位图会把一张多子图 Figure 拆成碎片 |
| 标签自动识别 | **纯离线、不是 AI**：中文分词 + 按「标题 ×12 / 摘要 ×6 / 正文 ×1」分区分权 + TF-IDF 排序，并用一个越用越准的本地语料给领域通用词降权 |
| 幻灯片编辑 | 内置 Lectern 编辑器（Apache-2.0）；也可点「打开」交给系统 PowerPoint / WPS |
| 标签筛选与搜索 | 首页按标签、标题、文件名实时过滤；标签多了只露 5 个，其余收进「⋯」按钮 |
| 数据只在本机 | IndexedDB + WebView2 本地存储，清除浏览器数据即清空 |

## 快速开始

### 方式一：直接下载 exe（推荐，普通用户）

到 [Releases](../../releases) 下载 `组会工作台.exe`（约 44 MB，仅 Windows）。

**这一个文件就是全部** —— HTML 界面、幻灯片引擎、PDF 渲染库、中文分词词典都已内嵌，
单独拷到任何一台 Windows 上双击就能用，旁边不需要再放任何文件。

### 方式二：从源码跑（开发者）

```bash
pip install -r requirements.txt
python app/desktop.py
```

首次运行需要 Python 3.10+。依赖共 7 个，都是纯 pip 可装的包。

### 方式三：自己打包

```bash
pip install -r requirements.txt pyinstaller
python -m PyInstaller --clean --noconfirm build/组会工作台.spec
```

产物在 `dist/组会工作台.exe`。打包脚本里记录了三条容易踩的坑（jieba 冗余数据、
pypdfium2 体积取舍、路径不能写死），改之前建议先读 `build/组会工作台.spec` 顶部的注释。

## 目录结构

```
app/
  desktop.py          桌面壳（pywebview）：本机 HTTP 桥 + 论文解析 + PPTX 写入 + 编辑器静态服务
  组会工作台.html      前端成品（单文件，2.4 MB）
  icon.ico / icon.png 应用图标
  说明.txt             使用者说明
  编辑器/              Lectern 幻灯片编辑器（Apache-2.0）+ 自写适配层 _zuhui_embed.js
  源码/                前端源码与构建脚本（见其 README.md）
设计/                  图标与壁纸的生成脚本、方案稿
build/                 PyInstaller 打包脚本
tools/                 端到端自检脚本 + 夹具生成器
release/               发布用的 exe（不在 git 里，走 Releases）
```

## 前端怎么改

前端是**源码 → 单文件成品**两段：

```bash
cd app/源码
python build_minimal.py            # 把 vendor/ 内联回 ../组会工作台.html
python build_minimal.py --check    # 只校验「重建结果与现有成品是否逐字节一致」
```

日常要改的是 `app/源码/vendor/app.js`、`app/源码/vendor/app.css`。改完跑一次
`build_minimal.py`；**只改前端不重打 exe** —— 桌面壳优先读 exe 同级的
`组会工作台.html`。只有改 `desktop.py` 才必须重新打包。

## 自检

```bash
python tools/make_fixtures.py          # 生成最小测试夹具（无版权问题）
python tools/_verify_rename.py         # 改组会名称：10 项端到端断言
python tools/_verify_softrefresh.py    # 改名 / 改标签后阅读页不闪回：9 项断言
```

自检用本机 Chrome 无头打开页面、注入假记录，不依赖真实论文。夹具由
`make_fixtures.py` 用 python-pptx 和 Pillow 现造，同样是 KB 级、无版权负担。

## 技术栈

- 桌面壳：Python 3.10+ / pywebview 6（Edge WebView2）
- PPTX：python-pptx 1.0 / pypdf 6 / pypdfium2 5 / lxml 6 / Pillow 12
- 中文分词：jieba 0.42
- 前端：原生 JS + 自写 3D 圆柱首页；PptxGenJS 与 ZRender 两个打包库内联在 `源码/vendor/`
- 幻灯片编辑器：Lectern（VibeOffice，Apache-2.0）

## 已知限制

- 仅支持 Windows（依赖 Edge WebView2，Win10/11 自带）
- 论文只支持 PDF；幻灯片只支持 PPTX
- 标签识别靠词典与词频，认不出论文里太新的术语，识别不准直接手改即可
- 内置编辑器是完整可用的，但对复杂动画、SmartArt 的支持不完整 —— 这类文件建议用「打开」交给 PowerPoint

## 第三方许可

本项目引入的第三方组件及其许可见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。
其中 Lectern 幻灯片编辑器为 Apache-2.0，其引用的组件许可随
`app/编辑器/common/licenses/` 一并分发。

## 许可证

[MIT](LICENSE)。Copyright (c) 2026 NIRVANA
