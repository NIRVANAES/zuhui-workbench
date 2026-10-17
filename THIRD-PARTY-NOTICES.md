# 第三方组件与许可声明

本项目（组会工作台）自身以 MIT 许可发布，Copyright (c) 2026 NIRVANA，
许可全文见根目录 `LICENSE`。
下面列出它引入的第三方组件、各自的许可，以及许可文本所在的位置。

分发本项目（含打包后的 exe）时，请一并保留本文件与 `app/编辑器/common/licenses/`
目录下的许可文本。

---

## 1. Lectern 幻灯片编辑器（VibeOffice）

- **用途**：内置幻灯片编辑器的前端本体。
- **许可**：Apache-2.0
- **位置**：`app/编辑器/lectern/`（另含 `common/`、`fonts/`、`icons/`，以及本项目自写的
  适配层 `_zuhui_embed.js`）
- **说明**：Apache-2.0 允许商用、修改与再分发，条件是保留版权与许可声明、
  标注被修改的文件。本仓库未单独放置 Lectern 的 LICENSE 全文，
  上游许可见 <https://www.apache.org/licenses/LICENSE-2.0>。

## 2. Lectern 引用的组件（许可文本随仓库分发）

许可文本位于 `app/编辑器/common/licenses/`：

| 文件 | 组件 | 许可 |
|---|---|---|
| `apache-openoffice-NOTICE.txt` | Apache OpenOffice | Apache-2.0（NOTICE） |
| `commonmark.js-LICENSE.txt` | commonmark.js | BSD-2-Clause |
| `microsoft-vba-docs-LICENSE.txt` | Microsoft VBA 文档 | MIT |
| `norvig-spell-LICENSE.txt` | Norvig 拼写校正 | MIT |
| `openxml-sdk-LICENSE.txt` | OpenXML SDK | MIT |
| `puff-LICENSE.txt` | puff | Zlib |
| `sheetjs-ssf-NOTICE.txt` | SheetJS SSF | Apache-2.0（NOTICE） |

字体许可位于 `app/编辑器/fonts/LICENSES.txt`。

## 3. Python 依赖（运行时）

均通过 pip 安装，许可见各自项目主页：

| 包 | 版本（开发时） | 许可 |
|---|---|---|
| pywebview | 6.2.1 | BSD-3-Clause |
| python-pptx | 1.0.2 | MIT |
| pypdf | 6.20.1 | BSD-3-Clause |
| pypdfium2 | 5.14.0 | Apache-2.0 / BSD-3-Clause（PDFium） |
| Pillow | 12.3.0 | HPND（MIT-Cmu） |
| lxml | 6.1.3 | BSD-3-Clause |
| jieba | 0.42.1 | MIT |

## 4. 前端内联的两个打包库

位于 `app/源码/vendor/`，由上游构建产物被打包进单文件 HTML：

| 文件 | 用途 |
|---|---|
| `lib-1-docx.js` | 前端读取 / 渲染 DOCX |
| `lib-2-zrender.js` | 2D 绘图与图表渲染（含 ZRender、d3） |

> ⚠️ **来源待确认**：这两个文件是反推重建前端源码时从成品 HTML 中抽出的，
> 本仓库**未能确认**它们的原始项目与版本号，因此也未在此声明其许可。
> 如果你知道它们的上游出处，请补充到本节；在确认之前，请勿将其视为
> 已获授权公开发布的组件。

## 5. 图标与背景

- 应用图标 `app/icon.ico`、`app/icon.png`，以及 `设计/` 下的方案稿，
  由 `设计/make_icon.py`、`设计/make_variants*.py` 生成本项目自有素材，随 MIT 许可发布。
- 首页背景图由 `设计/make_wallpaper.py` 生成。
