# 组会工作台 · 前端源码

> 2026-10-16 重建。原来的 `~/.workbuddy/skills/paper-deck-workbench/` 整个目录
> （含 `minimal.src.html` 与 `build_minimal.py`）在清理时被删掉了，本目录是从
> **成品 `组会工作台.html` 反推重建**的 —— 已验证重建结果与原成品**逐字节一致**。

## 结构

```
组会工作台/
├── 组会工作台.html      ← 单文件成品（双击即用，也是 exe 内嵌的那份）
├── desktop.py           ← 桌面壳（Python）
├── 组会工作台.exe       ← 打包产物
├── icon.png             ← 图标
└── 源码/
    ├── minimal.src.html      ← 前端骨架（HTML + 外部引用）
    ├── build_minimal.py      ← 构建：内联 vendor/ → ../组会工作台.html
    └── vendor/
        ├── bg-shader.js         12085  背景着色器（自写，注释在文件头）
        ├── lib-1-docx.js       642433  打包库：实测含 docx×64 / JSZip / pako / React
        ├── lib-2-zrender.js  1361034  ⚠️ 实测就是 pptx-preview 的打包产物
        ├── app.js              58874  应用脚本 ← **日常改的就是这个**
        ├── app.css             25092  应用样式（라일락 淡紫主题）
        └── bgfig.css          307264  背景应援图样式
```

## 日常怎么改

```bash
cd 组会工作台/源码
# 改 vendor/app.js（应用逻辑）或 vendor/app.css（样式）或 minimal.src.html（结构）
python build_minimal.py           # 内联回 ../组会工作台.html
python build_minimal.py --check   # 校验：重建结果与现有成品是否逐字节一致
```

改完 HTML 要**重打 exe** 才会生效（exe 里内嵌的是打包那一刻的 HTML）：

```bash
cd ..                                     # 回到 组会工作台/
python -m PyInstaller --clean --noconfirm --workpath build --distpath dist 组会工作台.spec
cp dist/组会工作台.exe 组会工作台.exe      # 部署
```

## ⚠️ 已知缺口与更正（2026-10-16 逐条核实，别照抄旧结论）

1. **两个打包库查明了身份，但版本/出处仍不能 100% 确认**（2026-10-16 补充实测）：
   - `lib-1-docx.js` 内 `mammoth` 7 处 / `JSZip` 11 / `pako` 19 → 是 **mammoth 的浏览器 bundle**
     （.docx 渲染），对应旧版 `vendor/mammoth.browser.min.js`。
   - `lib-2-zrender.js` 内 **`pptx-preview` 8 处**、`zrender` 2、`echarts` 8、
     版本串 `3.10.1` / `4.17.21` → 它其实就是 **`pptx-preview.umd.js`**
     （内含 zrender / d3），文件名里的 "zrender" 是当初命名时的误判。
   - ⚠️ **这一条有授权含义**：项目交接文档明确写过，**pptx-preview 作者的 README
     声明"不得发布到互联网平台、不得直接修改源码转为自有项目开源"**。
     照现在的文件名（"zrender"）很容易被当成宽松许可的库而误传到公开仓库 ——
     **要公开这个项目，这个文件以及内联了它的成品 HTML 都不能提交**。
2. **`bgfig.css` 生成脚本确实没了**。它头部写着「由 `make_bg_figures.py` 生成，
   勿手改」，那个脚本（以及它引用的 `design/应援图版-设计哲学.md`）都不在本机了
   —— 也就是说这份背景图样式**现在只能手改、不能重新生成**。
   ⚠️ 但**设计哲学本身没全丢**：`组会工作台/设计/设计哲学.md`（3280 B，라일락
   宣言：纸白/淡紫/深紫 + 霓虹黄限 1% 面积、光的四层噪声、玻璃真折射）还在，
   它同时覆盖「界面与图版」。调图版前先读这份，别以为没有依据。
3. ~~`vendor/app.js` 是压缩后形态，变量名被压过，可读性差~~ ——
   **这条 2026-10-16 核实后作废：app.js 没有压缩，完全可读。**
   实测：开头就是 `(function(){ 'use strict'; var DB_NAME='zuhui-workbench'…`，
   内含 `/* */` 注释 400 处、`//` 注释 77 处，函数名都是 `cylApply` / `bindGlobal` /
   `listBodyHTML` / `makeTagAuto` 这种有意义的名字。当初写「被压过」，八成是把
   58874 **字符** 看成了 68474 **字节**（差的那 9600 是中文注释的多字节部分），
   又看到单行长注释误判成 minify。**`vendor/app.js` 就是可以正常维护的源码。**

## 打包前后要盯的几件事（2026-10-16 实测）

**exe 体积参考**：本次构建产物 `32,780,806 字节`，md5 `708c7f48605d11f7f4e61c51c0e5e77f`
（2026-10-16 17:08）。体积突变时先查下面的第 2、3 条。

1. **`find_html()` 先读 exe 同目录的 `组会工作台.html`，读不到才用内嵌副本。**
   好处：改完 HTML 不重打 exe 也能立刻生效；**代价**：只把 exe 拷到别处，
   界面会悄悄退回打包那一刻的旧版。所以「改了 HTML」和「重打了 exe」是两件事，
   要一起做。
2. **本机没装 UPX**，spec 里的 `upx=True` 会被**静默跳过**（不报错、只是不压缩）。
   换台装了 UPX 的机器构建，体积会明显变小 —— 这是正常的，不是丢文件。
3. **`pyinstaller-hooks-contrib` 新版自带 `hook-jieba.py`**，它收集的数据文件
   **绕过了 spec 里那道 `_SKIP` 过滤**（那道过滤只作用于 `collect_all('jieba')`
   的返回值，管不到 hook 直接往 `a.datas` 里塞的东西）。实测因此多塞了 27 个文件：
   `jieba/lac_small` 22 + `jieba/posseg` 4 + `jieba/analyse` 1，正好是 spec 注释里
   点名要挡掉的那批。
   ✅ **2026-10-16 已修**：在 `组会工作台.spec` 的 `Analysis` 之后、`PYZ` 之前加了
   一道 `a.datas` 过滤（与 hooks 版本无关）。实测构建时打印
   `[spec] jieba 冗余数据文件剔除 27 个（datas 300 -> 273）`，
   exe 从 `48,558,316` 降到 `32,780,806` 字节；`jieba` 归档条目回到 17 个，
   抽词功能实测正常（`--tag-check` 跑 .docx 仍出 8 个中文标签）。
   > ⚠️ 顺带说明：新旧包体积差**不止**这 27 个文件 —— 老包的构建环境里还装着
   > `numpy` / `fontTools` / `charset_normalizer` 等**可选件**，本应用并不 import
   > 它们。缺 `fontTools` 只影响 pypdf 对少数 Type1/CFF 字体的解析，实测 9 篇论文
   > 抽出的字数差 ≤36 字（0.07%），标签结果无变化。
4. **验证不必开窗口**：`--editor-check <输出>`（检查 exe 内 `编辑器/` 能否被找到并由本地服务发出）、
   `--tag-check <论文> <输出>`（标签识别，
   会打印抽出字数／标题区／摘要区／参考文献截断／候选标签）、`--fig-check <论文> <输出>`
   （按页渲染 + 框选）都能在无桌面环境跑，是打包后最快的体检。
   `--selftest`（真开窗自检）**必须在有桌面的会话里跑**：在没有窗口站的进程里它会报
   `Main window failed to start`，那是环境问题，不代表打包坏了。
5. **`编辑器/` 必须一起打包**。它是内置幻灯片编辑器（VibeOffice · Lectern，Apache-2.0），
   spec 的 `datas` 里以 `('…/组会工作台/编辑器', '编辑器')` 整目录带入。
   运行时由 `desktop.py` 的 `_EditorHandler` 在 127.0.0.1 起只读静态服务发出（file:// 下
   子资源会被拦，所以必须走 http）。**删了它「编辑」按钮会提示资源缺失**，
   用 `--editor-check` 一眼能看出来。
   - 里面 `_zuhui_embed.js` 是**我们自己加的适配层**（不属于上游）：接收 postMessage 传来的
     pptx 字节并合成拖放打开；拦截 `<a download>` 把保存结果交回工作台，不落下载目录。
   - `lectern/index.html` 末尾多了一行 `<script src="../_zuhui_embed.js">`，
     升级上游时要把这行补回去，否则「编辑」打开后不会自动载入文件。
6. **规格文件里是绝对路径**（`组会工作台.spec` 的 `datas` 与入口脚本），换机器/换目录
   构建前必须先改，否则打不出包。

## 交互与动效：`app.css` 末尾那几段（⑤ ⑥）

`app.css` 里有一段集中的交互规则，改之前先读它自己的注释，别重复造：

| 段 | 管什么 |
|---|---|
| 时长/缓动变量（`--dur-1/2/3`、`--dur-press` 80ms、`--dur-lift` 160ms、`--ease-ios`、`--ease-out-quart`） | 全站动效节奏的唯一出处 |
| ① 按压反馈 | 按下立刻缩（80ms）、松手慢慢回（160ms）——「快下慢起」 |
| ② 首页卡片 | 卡片的 transform 被 `floaty` 漂浮动画占着，按压改走 `::after` 状态层 |
| ③ 阅读页进场 | 只动 `opacity`/`translateY`（**别用 scale**，PDF iframe 会每帧重新栅格化） |
| ④ 弹层 | `250ms` + `scale(.96)`，配 `@starting-style` 做进退场 |
| ⑤ 减少动效 | `prefers-reduced-motion` 下时长压到 1ms |
| **⑥ 去「生硬」**（2026-10-16 加） | 见下 |

### ⑥ 为什么加它（三处硬边）

1. **tap highlight**：WebView2 / 触屏在**按下那一瞬间**会盖一层灰蓝色高亮方块，
   它不受 `transition` 控制、盖在所有样式之上 —— 是整套交互里最硬的一下。
   关掉它（`-webkit-tap-highlight-color:transparent`），用 2 的按压反馈替代。
   这一条是从 Open Props 的按钮实现里学来的（`src/extra/buttons.css` 也显式关它）。
2. **只有「缩」没有「陷」**：真按钮按下去会连带投影收小、悬停时先抬起来。
   补上「悬停 `translateY(-1px)` + 一圈淡紫环 → 按下环收掉 + 投影收小 + `scale(.97)`」，
   比单纯 `filter:brightness()` 更像实体。
3. **禁用态硬切**：`.btn` 的 `transition-property` 里没有 `opacity`，变灰是「啪」的一下。
   补进属性列表。

参考：`argyleink/open-props` 的 `src/extra/buttons.css`（`--_highlight-size` 的用法、
关 tap highlight、disabled 的 `cursor:not-allowed`）与 `src/props.easing.css`（弹簧缓动数值）。

验证脚本：`E:/WorkBuddy/output/_test_button.py`（11 项，读**计算样式**断言，
不靠肉眼）——悬停 `matrix(1,0,0,1,0,-1)`、按下 `matrix(0.97,...)`、紫环收到 0。

## 改完怎么生效

- **只改 HTML/CSS/JS**：跑 `build_minimal.py` 就行，**不用重打 exe** ——
  `desktop.py` 的 `find_html()` 优先读 exe 同级目录的 `组会工作台.html`，
  改了立刻生效（这也是你能直接看到改动的原因）。
- **改了 `desktop.py`**：必须重打 exe。

## 与旧路径的对应

| 旧路径（已删除） | 新路径 |
|---|---|
| `skills/paper-deck-workbench/templates/minimal.src.html` | `组会工作台/源码/minimal.src.html` |
| `skills/paper-deck-workbench/build_minimal.py` | `组会工作台/源码/build_minimal.py` |
| `skills/paper-deck-workbench/vendor/*` | `组会工作台/源码/vendor/*` |

## 关于 `../paper-deck-workbench/`（**别当成本项目的源码用**）

项目根目录还有这么一个目录，容易看错。它是**更早的原型**（「论文·幻灯片 同步工作台」），
里面的 `template/app.js` 只有 33345 字节，而当前应用脚本是 **68474 字节** ——
差了近一倍，功能也不是一套。它自带 `build_workbench.py`（读 `template/app.css` +
`template/app.js` 合成单文件），正好说明**CSS/JS 分开就是原始设计**，
本目录的结构与之吻合。

它唯一还有用的是 `design/PHILOSOPHY.md`（设计哲学，3787 字节 / `c2d1e4c999`）
—— `bgfig.css` 头部引用的那份文档在这里，但版本与旧记录不一致，仅供参考。

## 抽取保真度的独立证据

抽出的 `vendor/bgfig.css` md5 = `3bbbfa3277`，与交接文档里旧路径
`templates/bg-figures.css` 记录的 md5 **完全一致** —— 说明抽取过程是字节级忠实的，
`vendor/` 里的六个文件可以直接当作原文件使用。
