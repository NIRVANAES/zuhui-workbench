/* the look (common/looks.css) and its layout before the first paint, from the saved choice (suite.js, VO.look);
   loaded first in every page's <head>, a script file rather than inline (the pages' Content-Security-Policy) */
try { var d = document.documentElement, l = localStorage.getItem('vibeoffice.look') || 'classic'; d.dataset.look = l; d.dataset.layout = l === 'paper2016' ? 'ribbon' : 'bars'; } catch (e) { /* storage off: the default look */ }
