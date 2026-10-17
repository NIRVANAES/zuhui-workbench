/* ============================================================================
   组会工作台 · 编辑器嵌入适配层（不属于 VibeOffice 原项目）
   ----------------------------------------------------------------------------
   作用：让 Lectern 能在工作台右栏的 iframe 里被驱动 ——
     ① 工作台用 postMessage 把 .pptx 字节推进来 → 合成一次拖放，让它打开；
     ② 它保存时走的是 <a download>，我们拦住、把字节交回工作台，不落下载目录；
     ③ 提供 save / 关闭 指令。

   协议（全部带 __zuhui 字段，避免和它自己的消息混在一起）：
     子 → 父： {__zuhui:'ready'} / {__zuhui:'opened'} / {__zuhui:'saved', bytes, name}
     父 → 子： {__zuhui:'open', bytes, name} / {__zuhui:'cmd', cmd:'save'}
   ========================================================================== */
(function () {
  if (!/[?&]embed=1/.test(location.search)) return;   // 直接用编辑器（未嵌入）时完全不干预

  function post(msg, transfer) {
    try { parent.postMessage(msg, '*', transfer || []); } catch (e) { /* 父窗口不在，忽略 */ }
  }

  /* ① 保存：拦住 <a download>，把字节交回工作台。
        不调原来的 click，所以不会在「下载」文件夹里留一份副本 —— 文件由工作台管理。 */
  var _click = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    var a = this;
    try {
      if (a.download && a.href && a.href.indexOf('blob:') === 0) {
        fetch(a.href)
          .then(function (r) { return r.blob(); })
          .then(function (b) { return b.arrayBuffer(); })
          .then(function (buf) { post({ __zuhui: 'saved', name: a.download, bytes: buf }, [buf]); })
          .catch(function (e) { post({ __zuhui: 'error', error: '读回保存结果失败：' + e }); });
        return;                       // ← 关键：模拟下载到此为止
      }
    } catch (e) { /* 落到下面的正常点击 */ }
    return _click.apply(a, arguments);
  };

  /* ② 打开：把字节包成 File，交给它自己的拖放入口（不需要改它的源码） */
  addEventListener('message', function (ev) {
    var d = ev.data;
    if (!d || d.__zuhui !== 'open' || !d.bytes) return;
    var app = document.getElementById('app');
    if (!app) { post({ __zuhui: 'error', error: '编辑器还没加载完' }); return; }
    try {
      var blob = new Blob([d.bytes], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' });
      var file = new File([blob], d.name || 'slides.pptx', { type: blob.type });
      var dt = new DataTransfer();
      dt.items.add(file);
      app.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
      post({ __zuhui: 'opened', name: file.name });
    } catch (e) {
      post({ __zuhui: 'error', error: '打开失败：' + e });
    }
  });

  /* ③ 指令：保存（发一次 Ctrl+S 给它自己的快捷键分发）*/
  addEventListener('message', function (ev) {
    var d = ev.data;
    if (!d || d.__zuhui !== 'cmd') return;
    if (d.cmd === 'save') {
      document.dispatchEvent(new KeyboardEvent('keydown', {
        key: 's', code: 'KeyS', ctrlKey: true, bubbles: true, cancelable: true
      }));
    }
  });

  post({ __zuhui: 'ready' });
})();
