# -*- coding: utf-8 -*-
"""用**真实** pptx 验证改名走 soft refresh、不重新解析幻灯片。

上一版自检用的是假 pptx（内容是 'PK fake...'，不是有效 zip），pptxPreview
直接报「不是有效的 zip」，右栏停在错误页 —— 于是 #deckHost 天然不存在，
那条断言是测试自己的错，不是产品 bug。这里改用 demo/ 里的真实样例。

要证明的是：改名只改两处文本节点（.rt / .rtags），#bodySlides 整棵子树
保持同一个 JS 对象身份，且翻页位置不变。

  python _verify_softrefresh.py
"""
from __future__ import annotations

import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

# 本脚本在 tools/ 下；应用成品在仓库根 ../app/；夹具由 make_fixtures 生成在
# tools/fixtures/（纯本地生成，无版权问题 —— 见 make_fixtures.py 顶部说明）。
# 也可用环境变量 ZUOHUI_HTML / ZUOHUI_PPTX / ZUOHUI_PDF 指向别处的文件。
import make_fixtures

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (pathlib.Path(os.environ["ZUOHUI_HTML"]) if os.environ.get("ZUOHUI_HTML")
        else ROOT / "app" / "组会工作台.html")
_FIX = make_fixtures.ensure()
PPTX = (pathlib.Path(os.environ["ZUOHUI_PPTX"]) if os.environ.get("ZUOHUI_PPTX")
        else _FIX["pptx"])
PDF = (pathlib.Path(os.environ["ZUOHUI_PDF"]) if os.environ.get("ZUOHUI_PDF")
       else _FIX["pdf"])
# 截图固定落在 tools/ 下（不随 ROOT 定义漂移，否则会跑到仓库根目录去）
SHOTS = pathlib.Path(__file__).resolve().parent / "_shots_rename"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name +
          (("  -> " + str(extra)) if extra else ""))


SEED = """
async ([pptxB64, pdfB64]) => {
  const bl = (t) => new Blob([Uint8Array.from(atob(t), c => c.charCodeAt(0))]);
  await new Promise((res, rej) => {
    const q = indexedDB.open('zuhui-workbench', 2);
    q.onupgradeneeded = () => { const d = q.result;
      if (!d.objectStoreNames.contains('meetings')) d.createObjectStore('meetings', {keyPath:'id'}); };
    q.onsuccess = () => { const db = q.result; const t = db.transaction('meetings','readwrite');
      t.objectStore('meetings').put({ id:'mreal01', title:'真实文件测试', createdAt:Date.now(),
        tags:['相变材料','太赫兹'],
        paper:{ name:'demo_paper.pdf', size:pdfB64.length, kind:'pdf', blob: bl(pdfB64) },
        slides:{ name:'demo_slides.pptx', size:pptxB64.length, kind:'pptx', blob: bl(pptxB64) } });
      t.oncomplete = () => res(); t.onerror = () => rej(t.error); };
    q.onerror = () => rej(q.error);
  });
  return true;
}
"""


def main():
    import base64
    SHOTS.mkdir(exist_ok=True)
    pptx_b64 = base64.b64encode(PPTX.read_bytes()).decode()
    pdf_b64 = base64.b64encode(PDF.read_bytes()).decode()
    errors = []

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.emulate_media(reduced_motion="reduce")   # 停掉首页卡片动画，保证点击稳定
        page.on("pageerror", lambda e: errors.append("PAGEERROR: %s" % e))
        page.on("console", lambda m: errors.append("CONSOLE: %s" % m.text) if m.type == "error" else None)

        page.goto(HTML.resolve().as_uri() + "#nomotion", wait_until="load")
        page.wait_for_timeout(1000)
        page.evaluate(SEED, [pptx_b64, pdf_b64])
        page.reload(wait_until="load")
        page.wait_for_timeout(1000)

        page.locator(".row .main").first.click()
        # 真实 pptx 解析比假文件慢，多等一会儿
        for _ in range(40):
            page.wait_for_timeout(250)
            if page.locator("#deckHost").count() and page.locator("#pgNum").inner_text() != "— / —":
                break
        check("真实 pptx 已渲染出幻灯片", page.locator("#deckHost").count() == 1)
        pages = page.locator("#pgNum").inner_text()
        check("幻灯片页数已识别", "—" not in pages, pages)
        print("      页码指示:", pages)

        # 翻到第 3 页，制造一个「页码位置」当作 soft refresh 的探针
        page.click("#pgNext"); page.click("#pgNext")
        page.wait_for_timeout(600)
        before_page = page.locator("#pgNum").inner_text()
        check("已翻到第 3 页", before_page.strip().startswith("3"), before_page)

        # 在 DOM 上打身份标记：soft refresh 绝不能重建这两棵子树
        mark = page.evaluate("""() => {
          const app = document.getElementById('app');
          const sl = document.getElementById('bodySlides');
          window.__idApp = app; window.__idSlides = sl;
          app.__mark = 1; sl.__mark = 1;
          return true;
        }""")
        check("身份标记已打", mark is True)

        # 改名
        page.click("#rRename"); page.wait_for_timeout(350)
        page.fill("#rnInput", "改名后仍停在第 3 页")
        page.click("#rnSave")
        page.wait_for_timeout(900)

        print("\nsoft refresh 验证：")
        check("标题已更新",
              "改名后仍停在第 3 页" in page.locator(".rt").inner_text(),
              page.locator(".rt").inner_text())
        check("#app 是同一个 DOM 对象（没整页重建）",
              page.evaluate("() => document.getElementById('app') === window.__idApp"))
        check("#bodySlides 是同一个 DOM 对象（PPT 没被重新解析）",
              page.evaluate("() => document.getElementById('bodySlides') === window.__idSlides"))
        check("#app 身上的标记还在",
              page.evaluate("() => document.getElementById('app').__mark === 1"))
        check("#deckHost 还在（幻灯片实例活着）", page.locator("#deckHost").count() == 1)
        after_page = page.locator("#pgNum").inner_text()
        check("翻页位置没被重置", after_page == before_page,
              "%s -> %s" % (before_page, after_page))
        check("标签仍在（软刷新也刷标签）",
              page.locator(".rtags .tg").count() == 2,
              page.locator(".rtags .tg").count())
        page.screenshot(path=str(SHOTS / "06-softrefresh-real-pptx.png"), full_page=True)

        # 标签弹层仍可独立工作（soft refresh 改的 .rtags 是它共用的节点）
        page.click("#rTagEdit"); page.wait_for_timeout(300)
        check("标签弹层仍能打开", page.locator("#tagDlg[open]").count() == 1)
        check("标签弹层预填正确",
              page.input_value("#tgInput") == "相变材料 太赫兹", page.input_value("#tgInput"))
        page.click("#tgCancel"); page.wait_for_timeout(200)

        # 连续改名 5 次，确认不累积副作用
        for i in range(5):
            page.click("#rRename"); page.wait_for_timeout(220)
            page.fill("#rnInput", "第 %d 次改名" % (i + 1))
            page.click("#rnSave"); page.wait_for_timeout(450)
        check("连续改名 5 次后标题正确",
              page.locator(".rt").inner_text().strip() == "第 5 次改名",
              page.locator(".rt").inner_text())
        check("连续改名后 PPT 仍同一个对象",
              page.evaluate("() => document.getElementById('bodySlides') === window.__idSlides"))
        check("连续改名后页码未重置",
              page.locator("#pgNum").inner_text() == before_page,
              page.locator("#pgNum").inner_text())

        page.click("#rBack"); page.wait_for_timeout(600)
        check("回首页列表显示最后一次改名",
              "第 5 次改名" in page.locator(".row .t").first.inner_text(),
              page.locator(".row .t").first.inner_text())

        # 搜索断言修正：数据里与「相变」匹配的是标签，不是旧标题
        page.fill("#fSearch", "相变")
        page.wait_for_timeout(350)
        check("按标签字搜索命中（组字链路）", page.locator(".row").count() == 1,
              page.locator(".row").count())
        page.fill("#fSearch", "第 5 次改名")
        page.wait_for_timeout(350)
        check("按新标题搜索命中", page.locator(".row").count() == 1,
              page.locator(".row").count())
        page.press("#fSearch", "Escape"); page.wait_for_timeout(300)

        # 清理：走真实 UI 路径（点「移除」→ 确定），顺便验证移除功能没被改名改动影响
        page.locator(".row .rm").first.click()
        page.wait_for_timeout(300)
        check("移除需二次确认", page.locator(".row .confirm").count() == 1)
        page.locator(".row .confirm .yes").first.click()
        page.wait_for_timeout(700)
        check("移除后列表清空", page.locator(".row").count() == 0,
              page.locator(".row").count())
        check("移除后库里也空",
              page.evaluate("""() => new Promise(r => {
                const q = indexedDB.open('zuhui-workbench', 2);
                q.onsuccess = () => { const g = q.result.transaction('meetings','readonly')
                    .objectStore('meetings').getAll(); g.onsuccess = () => r(g.result.length); };
              })""") == 0)
        check("列表空时显示空状态", page.locator(".empty").count() == 1)

        b.close()

    print("\n" + "=" * 60)
    # ⚠️ 这两类控制台信息是「设计如此」，不算页面错误：
    #    ① favicon / icon.png 等同目录资源 404；
    #    ② exe 没开时，页面会自动探测本机接口（127.0.0.1:39177~39186），
    #       每个端口必然报一次 ERR_CONNECTION_REFUSED —— 这正是
    #       「网页版自动连上开着的 exe、连不上就退回基础功能」的正常表现。
    _NOISE = ("favicon", "icon.png", "err_connection_refused")
    real = [e for e in errors
            if not any(n in e.lower() for n in _NOISE)]
    check("无页面错误", not real, real[:5])
    print("PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  - 失败:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
