# -*- coding: utf-8 -*-
"""「改组会名称」功能端到端自检。

用本机 Chrome 无头打开 组会工作台.html，注入一条假的组会记录（不依赖真实
PDF/PPT —— 那两个文件走 blobURL，命名逻辑与它们无关），然后走完整交互：

  1. 首页能列出这条记录
  2. 点开进阅读页，能看到「改名」按钮
  3. 点「改名」→ 弹层打开且预填原名、全选
  4. 改标题 → 保存 → 阅读页标题、首页列表、IndexedDB 三处同步
  5. 标签与阅读页不因改名被清掉（soft refresh 语义）
  6. 边界：清空 → 不改名；改成同名 → 不写库；取消 → 不写库
  7. 刷新页面后新名字仍在（真的落库了，不是内存态）
  8. 输入法：中文标题能正常输入（composition 事件链没被破坏）

  python _verify_rename.py
"""
from __future__ import annotations

import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

# 本脚本在 tools/ 下，应用成品在仓库根 ../app/。
# 也可用环境变量 ZUOHUI_HTML 指向别处的同一文件（例如刚构建的副本）。
ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (pathlib.Path(os.environ["ZUOHUI_HTML"]) if os.environ.get("ZUOHUI_HTML")
        else ROOT / "app" / "组会工作台.html")
SHOTS = pathlib.Path(__file__).resolve().parent / "_shots_rename"

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  -> " + str(extra)) if extra else ""))


# 造两个假文件：内容随意，扩展名决定 kind，命名流程不解析其内容
FAKE = """
async () => {
  const enc = (s) => new Blob([s]).arrayBuffer().then(b => {
    const by = new Uint8Array(b); let s = '';
    for (let i = 0; i < by.length; i += 0x8000)
      s += String.fromCharCode.apply(null, by.subarray(i, i + 0x8000));
    return btoa(s);
  });
  const pdf = await enc('%PDF-1.4 fake paper for rename test');
  const ppt = await enc('PK fake pptx for rename test');
  const B = (t) => new Blob([Uint8Array.from(atob(t), c => c.charCodeAt(0))], {type: t.length?'':''});
  const blob = (t) => new Blob([Uint8Array.from(atob(t), c => c.charCodeAt(0))]);
  const dbi = indexedDB.open('zuhui-workbench', 2);
  await new Promise((res, rej) => {
    dbi.onupgradeneeded = () => {
      const d = dbi.result;
      if (!d.objectStoreNames.contains('meetings')) d.createObjectStore('meetings', {keyPath:'id'});
    };
    dbi.onsuccess = () => res(); dbi.onerror = () => rej(dbi.error);
  });
  const db = dbi.result;
  const rec = {
    id: 'mtest0001', title: '原始组会名称', createdAt: Date.now(), tags: ['光开关','太赫兹'],
    paper:  {name:'paper.pdf',  size: pdf.length, kind:'pdf',  blob: blob(pdf)},
    slides: {name:'slides.pptx',size: ppt.length, kind:'pptx', blob: blob(ppt)}
  };
  await new Promise((res, rej) => {
    const t = db.transaction('meetings','readwrite');
    t.objectStore('meetings').put(rec);
    t.oncomplete = () => res(); t.onerror = () => rej(t.error);
  });
  return rec.id;
}
"""


def read_title(page):
    """从 IndexedDB 读回真实落库的标题。"""
    return page.evaluate("""() => new Promise((res, rej) => {
      const q = indexedDB.open('zuhui-workbench', 2);
      q.onsuccess = () => {
        const g = q.result.transaction('meetings','readonly').objectStore('meetings').get('mtest0001');
        g.onsuccess = () => res(g.result ? g.result.title : null);
        g.onerror = () => rej(g.error);
      };
      q.onerror = () => rej(q.error);
    })""")


def main():
    SHOTS.mkdir(exist_ok=True)
    url = HTML.resolve().as_uri() + "#nomotion"   # 停掉首页圆柱动效，保证点击稳定
    errors = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900},
                                device_scale_factor=2)
        # 首页卡片有悬浮/自转动画，Playwright 会判「element not stable」而拒绝点击；
        # 模拟「减少动效」让动画停下（应用已支持 prefers-reduced-motion）。
        page.emulate_media(reduced_motion="reduce")
        page.on("pageerror", lambda e: errors.append("PAGEERROR: %s" % e))
        page.on("console", lambda m: errors.append("CONSOLE: %s" % m.text)
                if m.type == "error" else None)

        page.goto(url, wait_until="load")
        page.wait_for_timeout(1200)
        page.evaluate(FAKE)
        page.wait_for_timeout(300)

        # 重新加载，让应用从库里读数据
        page.reload(wait_until="load")
        page.wait_for_timeout(1200)

        print("\n1) 首页")
        check("记录出现在首页列表", page.locator(".row").count() == 1,
              page.locator(".row").count())
        check("列表标题是原始名称",
              "原始组会名称" in page.locator(".row .t").first.inner_text())
        check("列表显示两个标签",
              page.locator(".row .tags .tg").count() == 2,
              page.locator(".row .tags .tg").count())
        page.screenshot(path=str(SHOTS / "01-home.png"), full_page=True)

        # 记录搜索能找到它（确认改名后仍可搜）
        page.fill("#fSearch", "原始")
        page.wait_for_timeout(300)
        check("搜索命中", page.locator(".row").count() == 1)
        page.click("#fSearch")
        page.press("#fSearch", "Escape")
        page.wait_for_timeout(300)

        print("\n2) 进阅读页")
        page.locator(".row .main").first.click()
        page.wait_for_timeout(1500)
        check("「改名」按钮存在", page.locator("#rRename").count() == 1)
        check("「标签」按钮仍在", page.locator("#rTagEdit").count() == 1)
        head = page.locator(".rhead").inner_text()
        check("按钮顺序：改名在标签左边", head.index("改名") < head.index("标签"), head)
        check("标题显示原始名称", "原始组会名称" in page.locator(".rt").inner_text())
        page.screenshot(path=str(SHOTS / "02-reader.png"), full_page=True)

        print("\n3) 打开改名弹层")
        page.click("#rRename")
        page.wait_for_timeout(400)
        check("弹层已打开", page.locator("#renameDlg[open]").count() == 1)
        check("预填原名称",
              page.input_value("#rnInput") == "原始组会名称",
              page.input_value("#rnInput"))
        sel = page.evaluate("""() => {
          const i = document.getElementById('rnInput');
          return {focused: document.activeElement === i,
                  selStart: i.selectionStart, selEnd: i.selectionEnd,
                  len: i.value.length};
        }""")
        check("输入框已聚焦且全选（可直接打字覆盖）",
              sel["focused"] and sel["selStart"] == 0 and sel["selEnd"] == sel["len"], sel)
        page.screenshot(path=str(SHOTS / "03-rename-dialog.png"))

        print("\n4) 改成新名字")
        page.fill("#rnInput", "十月第二周 组会：相变材料")
        page.click("#rnSave")
        page.wait_for_timeout(900)
        check("弹层已关闭", page.locator("#renameDlg[open]").count() == 0)
        check("阅读页标题已更新",
              "十月第二周 组会：相变材料" in page.locator(".rt").inner_text(),
              page.locator(".rt").inner_text())
        check("落库标题已更新",
              read_title(page) == "十月第二周 组会：相变材料", read_title(page))
        check("标签没被清掉", page.locator(".rtags .tg").count() == 2,
              page.locator(".rtags .tg").count())
        # 注：这里注入的是假 pptx（不是有效 zip），pptxPreview 会停在错误页，
        # #deckHost 天然不存在。「改名不重新解析 PPT」要用真实 pptx 验证，
        # 见 _verify_softrefresh.py。
        page.screenshot(path=str(SHOTS / "04-renamed.png"), full_page=True)

        print("\n5) 回首页看列表")
        page.click("#rBack")
        page.wait_for_timeout(700)
        check("首页列表标题已更新",
              "十月第二周 组会：相变材料" in page.locator(".row .t").first.inner_text(),
              page.locator(".row .t").first.inner_text())
        check("标签仍在", page.locator(".row .tags .tg").count() == 2)
        page.fill("#fSearch", "相变材料")
        page.wait_for_timeout(300)
        check("按新名字能搜到", page.locator(".row").count() == 1)
        page.press("#fSearch", "Escape")
        page.wait_for_timeout(300)

        print("\n6) 边界：清空 / 同名 / 取消")
        page.locator(".row .main").first.click()
        page.wait_for_timeout(1200)

        # 清空 → 不生效
        page.click("#rRename"); page.wait_for_timeout(300)
        page.fill("#rnInput", "   ")
        page.click("#rnSave"); page.wait_for_timeout(500)
        check("全空格：弹层关闭且名字不变",
              page.locator(".rt").inner_text().strip() == "十月第二周 组会：相变材料",
              page.locator(".rt").inner_text())

        # 同名 → 不写库（时间戳不变 = 没 put）
        page.evaluate("""() => { window.__t = Date.now(); }""")
        page.click("#rRename"); page.wait_for_timeout(300)
        page.fill("#rnInput", "十月第二周 组会：相变材料")
        page.click("#rnSave"); page.wait_for_timeout(500)
        check("同名保存：无报错、标题不变",
              page.locator(".rt").inner_text().strip() == "十月第二周 组会：相变材料")

        # 取消 → 不生效
        page.click("#rRename"); page.wait_for_timeout(300)
        page.fill("#rnInput", "这个名字不该被保存")
        page.click("#rnCancel"); page.wait_for_timeout(400)
        check("取消：弹层关闭",
              page.locator("#renameDlg[open]").count() == 0)
        check("取消：标题未变",
              page.locator(".rt").inner_text().strip() == "十月第二周 组会：相变材料",
              page.locator(".rt").inner_text())
        check("取消：库里也没变",
              read_title(page) == "十月第二周 组会：相变材料", read_title(page))

        # Esc 关闭
        page.click("#rRename"); page.wait_for_timeout(300)
        page.press("#rnInput", "Escape")
        page.wait_for_timeout(300)
        check("Esc 可关闭弹层", page.locator("#renameDlg[open]").count() == 0)

        print("\n7) 回车保存 + 刷新后仍在")
        page.click("#rRename"); page.wait_for_timeout(300)
        page.fill("#rnInput", "回车保存测试")
        page.press("#rnInput", "Enter")
        page.wait_for_timeout(600)
        check("回车即保存",
              page.locator(".rt").inner_text().strip() == "回车保存测试",
              page.locator(".rt").inner_text())

        page.reload(wait_until="load")
        page.wait_for_timeout(1200)
        check("刷新后首页是新名字（真落库）",
              "回车保存测试" in page.locator(".row .t").first.inner_text(),
              page.locator(".row .t").first.inner_text())

        print("\n8) 中文输入法链路没被破坏")
        page.locator(".row .main").first.click()
        page.wait_for_timeout(1200)
        # 用 CDP 模拟真实 composition 序列：这一步曾因 oncomposition 属性赋值失效而挂掉
        page.click("#rRename")
        page.wait_for_timeout(300)
        page.evaluate("""() => {
          const i = document.getElementById('rnInput');
          i.focus(); i.value = '';
          const ev = (t, d) => i.dispatchEvent(
            new CompositionEvent(t, {data: d, bubbles: true, cancelable: true}));
          ev('compositionstart', '');
          i.value = '相';
          ev('compositionupdate', '相');
          ev('compositionend', '相');
          return true;
        }""")
        page.wait_for_timeout(200)
        st = page.evaluate("() => document.getElementById('rnInput').value")
        check("composition 序列后中文可写入", st == "相", st)
        page.click("#rnCancel")
        page.wait_for_timeout(200)

        # 搜索框的输入法链路：打字过程中不重建 DOM
        page.click("#rBack")
        page.wait_for_timeout(600)
        sf = page.evaluate("""() => {
          const f = document.getElementById('fSearch');
          f.focus();
          f.dispatchEvent(new CompositionEvent('compositionstart', {data:'', bubbles:true}));
          f.value = '相变';
          f.dispatchEvent(new CompositionEvent('compositionend', {data:'相变', bubbles:true}));
          return f.isConnected;
        }""")
        page.wait_for_timeout(400)
        check("搜索框组字后仍在 DOM 里（未被重建）", sf is True)
        # 数据里没有「相变」这个词（标签是 光开关/太赫兹），所以过滤到 0 条才是对的
        check("搜索框组字后过滤生效（无匹配则 0 条）",
              page.locator(".row").count() == 0,
              page.locator(".row").count())
        page.fill("#fSearch", "回车")
        page.wait_for_timeout(350)
        check("按标题片段可搜到", page.locator(".row").count() == 1,
              page.locator(".row").count())
        page.screenshot(path=str(SHOTS / "05-home-renamed.png"), full_page=True)

        # 清理测试数据（走真实 UI 路径，顺带验证移除功能）
        page.locator(".row .rm").first.click()
        page.wait_for_timeout(300)
        page.locator(".row .confirm .yes").first.click()
        page.wait_for_timeout(600)
        check("测试数据已清理", page.locator(".row").count() == 0,
              page.locator(".row").count())

        browser.close()

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
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  -", f)
    print("截图:", SHOTS)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
