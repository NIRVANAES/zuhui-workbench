/* The suite's language choice, before the first paint (docs/i18n.md). Shared by every page.
 * zh-TW, zh-HK, zh-MO and zh-Hant select Traditional Chinese (zh-Hant); other Chinese tags select zh-CN.
 * This selects UI/document defaults. An opened document keeps its own language and fonts. */
(function () {
  'use strict';
  const VO = window.VO || (window.VO = {});
  const LANGS = [['auto', 'Auto'], ['en', 'English'], ['ja', '日本語'], ['ko', '한국어'], ['fr', 'Français'], ['de', 'Deutsch'],
    ['zh-CN', '简体中文'], ['zh-Hant', '繁體中文']];
  const normalize = (tag) => {
    const s = String(tag || '').trim().toLowerCase();
    if (/^zh-(?:tw|hk|mo|hant)(?:-|$)/.test(s)) return 'zh-Hant';
    if (s === 'zh' || s.startsWith('zh-')) return 'zh-CN';
    const base = s.split('-')[0];
    return base === 'qps' || LANGS.some(([id]) => id === base) ? base : null;
  };
  const store = (v) => {
    try { if (v == null) return localStorage.getItem('vibeoffice.lang') || 'auto'; localStorage.setItem('vibeoffice.lang', v); }
    catch (e) { return 'auto'; }
  };
  VO.lang = {
    normalize,
    list: () => LANGS.map(([id, name]) => ({ id, name })),
    get: () => normalize(store()) || 'auto',
    set(id) {
      id = normalize(id);
      if (!LANGS.some(([l]) => l === id) || id === store()) return;
      store(id);
      if ('BroadcastChannel' in window) { const channel = new BroadcastChannel('vibeoffice'); channel.postMessage('lang'); channel.close(); }
    },
    resolve(choice, languages) {
      const id = normalize(choice);
      if (id && id !== 'auto') return id;
      return (languages || []).map(normalize).find((l) => l && l !== 'auto' && l !== 'qps') || 'en';
    },
  };
  if (typeof document !== 'undefined' && typeof location !== 'undefined') {
    const choice = new URLSearchParams(location.search).get('lang') || VO.lang.get();
    const lang = VO.lang.resolve(choice, navigator.languages || [navigator.language]);
    document.documentElement.lang = lang === 'qps' ? 'qps-ploc' : lang;
  }
})();
