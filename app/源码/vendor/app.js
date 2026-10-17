
(function(){
'use strict';
var DB_NAME='zuhui-workbench', STORE='meetings', SET_STORE='settings';
var db=null, list=[], pending={paper:null,slides:null}, slotDefault={}, slotErr={},
    urls=[], openId=null, confirming=null;
var deckInst=null, deckEl=null, deckLW=0, deckLH=0, deckCount=0, deckIdx=0;
var searchQ='', activeTag=null, tagTarget=null, curMid=null, transView=false, swapTarget=null;

function $(s){return document.querySelector(s);}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function pad(n){return n<10?'0'+n:''+n;}
function fmtDate(ts){var d=new Date(ts);
  return d.getFullYear()+'年'+(d.getMonth()+1)+'月'+d.getDate()+'日 星期'+'日一二三四五六'[d.getDay()]+
         ' '+pad(d.getHours())+':'+pad(d.getMinutes());}
function fmtDateShort(ts){var d=new Date(ts);
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());}
function defaultTitle(){var d=new Date();return d.getFullYear()+'年'+(d.getMonth()+1)+'月'+d.getDate()+'日 组会';}
function fmtSize(n){return n>=1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.round(n/1024))+' KB';}

/* ---------------- 标签 / 搜索 / 阅读进度 ---------------- */
function tagsOf(m){return (m&&m.tags&&m.tags.length)?m.tags:[];}
function normTags(s){
  var out=[], seen={};
  String(s||'').split(/[,，、;；\s]+/).forEach(function(x){
    x=x.trim(); if(!x||seen[x]) return; seen[x]=1; out.push(x);
  });
  return out.slice(0,8);
}
function allTagSet(){
  var c={};
  list.forEach(function(m){tagsOf(m).forEach(function(t){c[t]=(c[t]||0)+1;});});
  return Object.keys(c).sort(function(a,b){return c[b]-c[a]||a.localeCompare(b,'zh');});
}
/* ---------------- 首页筛选栏的标签：默认只露 5 个 ----------------
   2026-10-17 用户要求：标签太多时不要全摊在首屏上，先给 5 个，其余收进一个
   「⋯ +N」按钮，点一下展开、再点收起。
   为什么是「重绘 DOM」而不是「CSS 裁高」：flex-wrap 容器用 max-height 裁，
   会在**行中间**切断，露出半个标签的下缘 —— 比不裁更难看。所以直接少渲染几个。
   展开态记在 tagsOpen 里：列表重绘（改名、筛选、搜索）不会把它收回去。 */
var TAG_LIMIT=5, tagsOpen=false;
function chipsInnerHTML(){
  var tags=allTagSet();
  if(!tags.length) return '';
  var all=(tagsOpen||tags.length<=TAG_LIMIT);
  var shown=all?tags:tags.slice(0,TAG_LIMIT);
  var rest=tags.length-shown.length;
  var h='<button class="chip'+(activeTag?'':' on')+'" type="button" data-tag="">全部</button>';
  h+=shown.map(function(t){
    return '<button class="chip'+(activeTag===t?' on':'')+'" type="button" data-tag="'+esc(t)+'">'+esc(t)+'</button>';
  }).join('');
  if(rest>0){
    h+='<button class="chip more" type="button" data-tagmore="1" title="展开全部 '+tags.length+' 个标签">'+
       '<i>⋯</i><b>'+rest+'</b></button>';
  }else if(all&&tags.length>TAG_LIMIT){
    h+='<button class="chip more" type="button" data-tagmore="1" title="收起">'+
       '<i class="up">⋯</i>收起</button>';
  }
  return h;
}
/* 只重绘筛选栏，不重建整页 —— 重建会连带清掉搜索框的内容与焦点 */
function paintChips(){
  var box=document.querySelector('.tools .chips'); if(!box) return;
  box.innerHTML=chipsInnerHTML();
  box.classList.toggle('open',tagsOpen);
  bindChips();
}
function bindChips(){
  Array.prototype.forEach.call(document.querySelectorAll('.chip[data-tag]'),function(c){
    c.onclick=function(){
      activeTag=c.getAttribute('data-tag')||null;
      /* 选中的标签如果落在折叠区外，用户会看到一个「on」的按钮根本不在眼前 ——
         这时自动展开，让选中态看得见。 */
      if(activeTag){
        var all=allTagSet();
        if(all.indexOf(activeTag)>=TAG_LIMIT) tagsOpen=true;
      }
      renderList();
      paintChips();
    };
  });
}
function matchQ(m){
  if(activeTag&&tagsOf(m).indexOf(activeTag)<0) return false;
  if(!searchQ) return true;
  var hay=[m.title,m.paper&&m.paper.name,m.slides&&m.slides.name,tagsOf(m).join(' ')]
    .join(' ').toLowerCase();
  return hay.indexOf(searchQ.toLowerCase())>=0;
}
function tagHTML(m){
  var t=tagsOf(m);
  return t.length?t.map(function(x){return '<i class="tg">'+esc(x)+'</i>';}).join(''):'';
}
/* 阅读进度放 localStorage：只为记一个页码去重写整条含 blob 的记录不划算 */
function progKey(id){return 'zw.prog.'+id;}
function getProg(id){try{return JSON.parse(localStorage.getItem(progKey(id))||'{}')||{};}catch(e){return {};}}
function setProg(id,o){try{localStorage.setItem(progKey(id),JSON.stringify(o));}catch(e){}}

var KINDS={
  pdf:{tag:'PDF',cls:'',label:'PDF'},
  docx:{tag:'Word',cls:'w',label:'Word 文档'},
  pptx:{tag:'PPT',cls:'p',label:'幻灯片'}
};
function kindOf(name){
  var n=String(name||'').toLowerCase();
  if(/\.pdf$/.test(n)) return 'pdf';
  if(/\.docx$/.test(n)) return 'docx';
  if(/\.pptx$/.test(n)) return 'pptx';
  if(/\.doc$/.test(n)) return 'legacy-doc';
  if(/\.ppt$/.test(n)) return 'legacy-ppt';
  return null;
}
function kindName(k){return (KINDS[k]||{}).tag||'—';}

/* ---------------- 存储 ---------------- */
function openDB(){return new Promise(function(res,rej){
  var q=indexedDB.open(DB_NAME,2);
  q.onupgradeneeded=function(){var d=q.result;
    if(!d.objectStoreNames.contains(STORE)) d.createObjectStore(STORE,{keyPath:'id'});
    if(!d.objectStoreNames.contains(SET_STORE)) d.createObjectStore(SET_STORE);};
  q.onsuccess=function(){res(q.result);};
  q.onerror=function(){rej(q.error);};});}
function dbAll(){return new Promise(function(res,rej){
  var t=db.transaction(STORE,'readonly'), q=t.objectStore(STORE).getAll();
  q.onsuccess=function(){res(q.result);}; q.onerror=function(){rej(q.error);};});}
function dbPut(r){return new Promise(function(res,rej){
  var t=db.transaction(STORE,'readwrite'); t.objectStore(STORE).put(r);
  t.oncomplete=function(){res();}; t.onerror=function(){rej(t.error);};});}
function dbDel(id){return new Promise(function(res,rej){
  var t=db.transaction(STORE,'readwrite'); t.objectStore(STORE).delete(id);
  t.oncomplete=function(){res();}; t.onerror=function(){rej(t.error);};});}

/* ---------------- 设置项：自定义背景图 ---------------- */
function setGet(k){return new Promise(function(res,rej){
  var t=db.transaction(SET_STORE,'readonly'), q=t.objectStore(SET_STORE).get(k);
  q.onsuccess=function(){res(q.result);}; q.onerror=function(){rej(q.error);};});}
function setPut(k,v){return new Promise(function(res,rej){
  var t=db.transaction(SET_STORE,'readwrite'); t.objectStore(SET_STORE).put(v,k);
  t.oncomplete=function(){res();}; t.onerror=function(){rej(t.error);};});}
function setDel(k){return new Promise(function(res,rej){
  var t=db.transaction(SET_STORE,'readwrite'); t.objectStore(SET_STORE).delete(k);
  t.oncomplete=function(){res();}; t.onerror=function(){rej(t.error);};});}

/* 三个背景槽位：l 左 / r 右 / c 角标。CSS 里带默认图，自定义时用内联 style 覆盖。 */
var BG_SLOTS=[
  ['l','左侧图','显示在首页左边'],
  ['r','右侧图','显示在首页右边'],
  ['c','角标小图','右上角的小图']
];
var bgURL={l:'',r:'',c:''};
function bgEl(k){var b=document.getElementById('bgfig'); return b?b.querySelector('.'+k):null;}
function bgApply(k){
  var el=bgEl(k); if(!el) return;
  if(bgURL[k]) el.style.backgroundImage='url("'+bgURL[k]+'")';
  else el.style.backgroundImage='';                 // 清空 -> 回落到 CSS 里的默认图
}
function bgApplyAll(){ BG_SLOTS.forEach(function(s){ bgApply(s[0]); }); }
function bgSet(k,blob){
  if(bgURL[k]){ try{URL.revokeObjectURL(bgURL[k]);}catch(e){} }
  bgURL[k]=blob?URL.createObjectURL(blob):'';
  bgApply(k);
}
function bgLoadAll(){
  return Promise.all(BG_SLOTS.map(function(s){
    return setGet('bg.'+s[0]).then(function(b){
      if(b instanceof Blob) bgURL[s[0]]=URL.createObjectURL(b);
    }).catch(function(){});
  })).then(bgApplyAll);
}
var bgPickSlot=null;
function paintBgRows(){
  var box=$('#bgRows'); if(!box) return;
  box.innerHTML=BG_SLOTS.map(function(s){
    var k=s[0], url=bgURL[k];
    return '<div class="bgrow" data-slot="'+k+'">'+
      '<div class="bgthumb'+(k==='c'?' c':'')+'"'+
        (url?' style="background-image:url(&quot;'+url+'&quot;)"':'')+'>'+(url?'':IMG_ICON)+'</div>'+
      '<div class="bgmeta"><b>'+s[1]+'</b><span>'+(url?'已自定义':'使用默认')+' · '+s[2]+'</span></div>'+
      '<div class="acts">'+
        '<button class="btn ghost sm" type="button" data-act="pick">选择图片</button>'+
        (url?'<button class="btn ghost sm" type="button" data-act="reset">恢复默认</button>':'')+
      '</div>'+
    '</div>';
  }).join('');
}
function openBgDlg(){ paintBgRows(); $('#bgDlg').showModal(); }

function blobURL(b,type){
  var blob=(b instanceof Blob&&b.type)?b:new Blob([b],{type:type||'application/pdf'});
  var u=URL.createObjectURL(blob); urls.push(u); return u;
}
function revokeAll(){urls.forEach(function(u){try{URL.revokeObjectURL(u);}catch(e){}});urls=[];
  deckInst=null; deckEl=null; deckCount=0; deckIdx=0;}

/* ---------------- 打开 / 另存 ----------------
   桌面版（pywebview）把 Blob 交给 Python 落地，再用系统默认程序打开；
   纯浏览器里没有这层桥，就退化成「下载」。 */
function fileToBase64(blob){
  return blob.arrayBuffer().then(function(buf){
    var bytes=new Uint8Array(buf), CH=0x8000, parts=[];
    for(var i=0;i<bytes.length;i+=CH){
      parts.push(String.fromCharCode.apply(null, bytes.subarray(i,i+CH)));
    }
    return btoa(parts.join(''));
  });
}
function nativeApi(){
  var w=window.pywebview;
  return (w&&w.api&&w.api.open_file)?w.api:null;
}
function downloadBlob(blob,name){
  var u=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=u; a.download=name||'file';
  document.body.appendChild(a); a.click();
  setTimeout(function(){URL.revokeObjectURL(u); a.remove();},2000);
}
function openExtern(rec){
  if(!rec||!rec.blob) return;
  var api=nativeApi();
  if(!api){ downloadBlob(rec.blob,rec.name); return; }
  fileToBase64(rec.blob).then(function(b64){
    return api.open_file(rec.name||'file',b64);
  }).then(function(r){
    if(r&&r!=='ok') alert('打不开这个文件：'+r);
  }).catch(function(e){ alert('打不开这个文件：'+e); });
}
function saveExtern(rec){
  if(!rec||!rec.blob) return;
  var api=nativeApi();
  if(!api){ downloadBlob(rec.blob,rec.name); return; }
  fileToBase64(rec.blob).then(function(b64){
    return api.save_file(rec.name||'file',b64);
  }).then(function(r){
    if(r&&r!=='ok'&&r!=='cancelled') alert('保存失败：'+r);
  }).catch(function(e){ alert('保存失败：'+e); });
}

/* ---------------- 首页 ---------------- */
function fileCell(side,rec){
  var k=KINDS[rec.kind||'pdf']||{tag:'—',cls:''};
  return '<span><em>'+(side==='slides'?'PPT':'论文')+'</em><i class="nm">'+esc(rec.name)+'</i>'+
    '<b class="tag '+k.cls+'">'+k.tag+'</b></span>';
}
function rowHTML(m){
  var thisOne = confirming===m.id;
  return '<div class="row" data-id="'+esc(m.id)+'">'+
    '<div class="main">'+
      '<div class="t">'+esc(m.title)+'</div>'+
      (tagsOf(m).length?'<div class="tags">'+tagHTML(m)+'</div>':'')+
    '</div>'+
    (thisOne
      ? '<div class="confirm"><button class="no" data-act="cancel">取消</button>'+
        '<button class="yes" data-act="drop">确定移除</button></div>'
      : '<button class="rm" data-act="rm" title="移除">✕</button>')+
  '</div>';
}
/* 3D 圆柱 + 宇宙漂浮：角度均布但加抖动、半径/高度/漂浮幅度全部随机（确定性伪随机） */
function rnd(s){ var x=Math.sin(s*127.1+311.7)*43758.5453; return x-Math.floor(x); }   // [0,1)
function cylBaseR(n){
  if(n<=1) return 0;                                   // 只有一张 → 居中，不要绕大圈
  return Math.round(Math.max(170, Math.min(320, (124+18)/(2*Math.sin(Math.PI/n))*1.3)));
}
function slotHTML(m,i,n){
  var step = n<=2 ? 60 : 360/n;                        // 两张时别放正对面（会被背面隐藏）
  var a = i*step + (rnd(i*3+1)-0.5)*step*0.44;          // 角度加抖动 → 不再整齐排一圈
  var R = Math.round(cylBaseR(n) + (rnd(i*3+2)-0.5)*70);// 半径抖动 → 前后错落有纵深
  var y = Math.round((rnd(i*3+3)-0.5)*200);             // 高度随机 → 上下不对齐
  var fx=(4+rnd(i*3+4)*9).toFixed(1), fy=(6+rnd(i*3+5)*10).toFixed(1);
  var fr=(1+rnd(i*3+6)*2.4).toFixed(2);
  var bd=(4.5+rnd(i*3+7)*3.5).toFixed(2), bdl=(rnd(i*3+8)*4).toFixed(2);
  return '<div class="cslot" style="--i:'+i+';--a:'+a.toFixed(2)+'deg;--y:'+y+'px;--R:'+R+'px;'+
    '--fx:'+fx+'px;--fy:'+fy+'px;--fr:'+fr+'deg;--bd:'+bd+'s;--bdl:'+bdl+'s">'+
    rowHTML(m)+'</div>';
}
/* 팔레트 调色盘 —— 本作的标识：一枚挖穿拇指孔的调色盘，颜料点用霓虹黄与淡紫 */
function palette(size){
  return '<svg viewBox="0 0 24 24" width="'+size+'" height="'+size+'" aria-hidden="true">'+
    '<ellipse cx="12" cy="12.7" rx="9.2" ry="7.4" fill="var(--lilac)"/>'+
    '<ellipse cx="6.9" cy="16.2" r="1.9" fill="var(--bg)"/>'+
    '<circle cx="9.1" cy="8.9" r="1.6" fill="var(--neon)"/>'+
    '<circle cx="13.3" cy="7.8" r="1.5" fill="#ffffff"/>'+
    '<circle cx="17.2" cy="9.3" r="1.5" fill="var(--lilacL)"/>'+
    '</svg>';
}
var PLUS='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" '+
  'stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>';
/* 外开图标：方框 + 出框箭头 */
var OPEN_ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '+
  'stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4l-8.6 8.6"/>'+
  '<path d="M18.5 14.5V19a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 19V7.5A1.5 1.5 0 0 1 5.5 6H10"/></svg>';
/* 图片图标：山 + 太阳 */
var IMG_ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '+
  'stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4.5" width="18" height="15" rx="2.6"/>'+
  '<circle cx="8.6" cy="9.6" r="1.7"/><path d="M3.6 16.6l4.9-4.3 3.6 3.1 3.1-2.6 5.2 4.4"/></svg>';

/* 列表主体与搜索框分开渲染：搜索时只重建 #listBody，
   输入框本身不重建 —— 否则输入法组字会被打断、光标也得靠 setSelectionRange 硬塞 */
function listBodyHTML(){
  var shown=list.filter(matchQ);
  if(!list.length){
    return '<div class="empty">'+
      '<div class="ei">'+palette(66)+'</div>'+
      '<div class="et">还没有组会记录</div>'+
      '<p class="es">点右上角「新建组会」，把论文和 PPT 拖进来</p>'+
      '<button class="btn" id="eNew">'+PLUS+'新建组会</button>'+
    '</div>';
  }
  if(!shown.length){
    return '<div class="empty"><div class="et">没有匹配的组会</div>'+
      '<p class="es">换个关键词，或点「全部」清掉标签筛选</p></div>';
  }
  return '<div class="group"><div class="cyl">'+
    shown.map(function(m,i){return slotHTML(m,i,shown.length);}).join('')+'</div></div>';
}
function listSubText(){
  if(!list.length) return '把论文和 PPT 放在一起看';
  var n=list.filter(matchQ).length;
  return n===list.length ? '' : '匹配 '+n+' / '+list.length+' 次组会';
}
/* 只刷列表，不碰搜索框 */
function renderList(quiet){
  var b=$('#listBody'); if(!b) return;
  b.innerHTML=listBodyHTML();
  /* quiet：从阅读页退回来时用。列表要更新（改名、改标签），
     但卡片不该再错峰浮现一次 —— 那看起来就是「同一屏重画了两遍」。 */
  if(quiet){ b.classList.add('quiet'); setTimeout(function(){ b.classList.remove('quiet'); },420); }
  startCyl();
  var sub=$('#listSub'); if(sub) sub.textContent=listSubText();
  var n=$('#eNew'); if(n) n.onclick=openDialog;
  var bgBtn=$('#eBg'); if(bgBtn) bgBtn.onclick=openBgDlg;
  Array.prototype.forEach.call(document.querySelectorAll('.chip[data-tag]'),function(c){
    c.classList.toggle('on',(c.getAttribute('data-tag')||null)===activeTag);
  });
}

/* ---------------- 首页 3D 圆柱：拖动旋转 + 慢速自转 ---------------- */
var cylRot=0, cylDragging=false, cylMoved=0, cylLastX=0, cylPauseUntil=0, cylRAF=0;
var cylVel=0, cylSpin=false, cylLastT=0, cylLastMoveT=0;   /* 甩动惯性：速度(度/毫秒) + 是否在滑行 */
var readerOrigin=null;   /* 打开阅读页时那一击的落点 —— 让阅读页从卡片处「长出来」 */
var NOMOTION=/nomotion/.test(location.hash);   // 自检脚本用 #nomotion 停掉动效，保证点击稳定
/* ⚠️ 2026-10-17 实测踩到的大坑：Windows 关掉「显示动画」后，Chromium/WebView2 会报
   prefers-reduced-motion:reduce。上一版据此把**全部**动效关掉了，结果用户明明要求
   「每一次点击都有反馈、打开窗口有过渡」，却一条都看不到（他自己的系统就是关的）。
   现在的规则：
     · 动效默认**开**，跟随应用自己的开关（localStorage），不交给系统默认值；
     · 关掉时不是「全灭」，而是把位移/缩放去掉、只留极短淡入（见 app.css 的 .nomotion 段）；
     · #nomotion（自检）仍然全关 —— 六套回归靠它保持与改动前一致。 */
var FXOFF=false;
try{ FXOFF=localStorage.getItem('zuhui-fx')==='off'; }catch(e){}
if(NOMOTION||FXOFF) document.documentElement.classList.add('nomotion');
/* 动效总开关：自检（#nomotion）或用户自己关掉时，退场动画一律跳过 ——
   否则弹层会在「已经透明、但还 open 着」的那 200ms 里继续挡住点击。 */
var REDUCED=NOMOTION||FXOFF;
/* 视图切换：首页 ⇄ 阅读页的 DOM 是整块换掉的，用 CSS 动画在这上面根本跑不干净 ——
   新视图的首次布局与栅格化会占住主线程，动画只有两三帧可画（实测透明度一步从
   0.064 跳到 0.681），看着就是「啪一下弹出来」。改用浏览器 View Transition：
   它把前后两帧各截一张图，交叉淡入交给合成器，主线程再忙也不会掉帧。
   #nomotion / 用户关掉动效时整条关掉，退回无过渡的同步路径。 */
var lastClip=null;     /* 上次打开时那张卡片的矩形，返回首页时用来「缩回去」 */
/* 阅读页正在收拢（closeReader 开始 → 移除完毕）。
   ⚠️ 2026-10-17 用户报「点插图之后点返回会重复一帧」：收拢动画有 320ms，
   而 renderPane 是**异步**的（arrayBuffer → preview → boot → goSlide 串了四段）。
   在这 320ms 里点返回，最后一段渲染会落进正在收拢的栏里 ——
   画面看起来就是「同一屏又画了一遍」，然后才收回去。
   判定放在这里而不是用 el.isConnected：收拢期间栏**还连着**文档，isConnected 挡不住。 */
var readerLeaving=false;
function paneDead(el){ return readerLeaving || !el || !el.isConnected; }
/* 弹层退场：原生 close() 是瞬时的（CSS 追不上），这里先挂 .closing 淡出，再真正关。
   直接在原型上包一层：全项目十几处 .close() 一个字都不用改。 */
/* 立即关闭：绕开下面的退场包装，直接调原始 close()。
   用户 2026-10-17 要求「插图弹层点 × 直接关，不要动画」——
   不能只把 CSS 动画删掉：包装里还有 260ms 兜底定时器，删了动画反而要干等 260ms 才关。 */
var __dlgCloseRaw=null;
function closeDlgNow(d){
  if(!d) return;
  d.classList.remove('closing');
  if(__dlgCloseRaw) __dlgCloseRaw.call(d);
  else d.close();
}
if(!REDUCED && window.HTMLDialogElement){
  var __dlgClose=HTMLDialogElement.prototype.close;
  __dlgCloseRaw=__dlgClose;                     // 留一份原始 close 给 closeDlgNow 用
  HTMLDialogElement.prototype.close=function(){
    var d=this;
    if(!d.open) return __dlgClose.call(d);
    if(d.classList.contains('closing')) return;          // 已经在退场，别叠两次
    d.classList.add('closing');
    var fin=function(){ d.classList.remove('closing'); __dlgClose.call(d); };
    var t=setTimeout(fin,260);                           // 兜底：transitionend 万一不来也能关掉
    d.addEventListener('transitionend',function h(e){
      if(e.target!==d||e.propertyName!=='opacity') return;
      clearTimeout(t); d.removeEventListener('transitionend',h); fin();
    });
  };
  var __dlgShow=HTMLDialogElement.prototype.showModal;
  HTMLDialogElement.prototype.showModal=function(){      // 进场前清掉残留状态
    this.classList.remove('closing');
    return __dlgShow.call(this);
  };
}
/* 圆柱：值没变就不写样式 —— 原来每帧无条件写 --rot 与 N 个 opacity，
   在二十几张卡片时会白白触发样式重算。 */
var cylRotSet=null;
function cylApply(){
  var c=document.querySelector('.cyl'); if(!c) return;
  var v=cylRot.toFixed(2);
  if(v===cylRotSet) return;
  cylRotSet=v; c.style.setProperty('--rot',v+'deg');
}
/* 按「离正面的角度」淡出侧面与背面的卡 —— 只留正面几张清晰，避免挤成一团 */
function cylFade(force){
  var s=document.querySelectorAll('.cslot');
  for(var i=0;i<s.length;i++){
    var a0=parseFloat(s[i].style.getPropertyValue('--a'))||0;
    var a=(cylRot+a0)%360; if(a>180)a-=360; if(a<-180)a+=360;
    var c=Math.cos(a*Math.PI/180);                 // 1=正面, 0=侧面, <0=背面
    var o=c<=0 ? 0 : Math.pow(c,0.7);
    if(!force && s[i]._o!==undefined && Math.abs(s[i]._o-o)<0.004) continue;   // 没变就不写样式
    s[i]._o=o; s[i].style.opacity=o.toFixed(3);
  }
}
var cylLastTs=0;
function cylTick(ts){
  if(!document.querySelector('.cyl')){ cylRAF=0; cylLastTs=0; return; }   // 不在首页 → 停掉循环
  if(!cylLastTs) cylLastTs=ts;
  var dt=(ts-cylLastTs)/1000; cylLastTs=ts;
  if(dt>0.12) dt=0.12;                                     // 切走再回来别一次跳太多
  if(cylSpin&&!cylDragging){
    /* 松手后的甩动惯性：指数衰减（约 0.6 秒滑停），并逐步交还给慢速自转。
       拖动过程中是 1:1 跟手的（cylApply 直接跟 pointermove），惯性只负责「放手之后」。 */
    cylRot+=cylVel*dt*1000;
    cylVel*=Math.exp(-3.4*dt);
    if(Math.abs(cylVel)<0.02){ cylVel=0; cylSpin=false; cylPauseUntil=performance.now()+600; }
    cylApply();
  } else if(!cylDragging && !NOMOTION && performance.now()>cylPauseUntil){
    /* 按时间转（15°/秒），不要按帧 —— 否则高刷屏会转得飞快 */
    cylRot-=15*dt; cylApply();
  }
  cylFade();
  cylRAF=requestAnimationFrame(cylTick);
}
function startCyl(){ cylRotSet=null; cylApply(); cylFade(true); if(!cylRAF) cylRAF=requestAnimationFrame(cylTick); }

function listHTML(){
  var tags=allTagSet(), tools='';
  if(list.length){
    tools='<div class="tools">'+
      '<label class="search">'+
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '+
        'stroke-linecap="round"><circle cx="10.6" cy="10.6" r="6.4"/><path d="M15.4 15.4L20 20"/></svg>'+
        '<input id="fSearch" type="search" autocomplete="off" placeholder="搜索组会名称、论文、PPT、标签…" value="'+esc(searchQ)+'">'+
      '</label>'+
      (tags.length?'<div class="chips'+(tagsOpen?' open':'')+'">'+chipsInnerHTML()+'</div>':'')+
    '</div>';
  }
  return '<div class="wrap">'+
    '<div class="eyebrow">'+palette(15)+'<span>라일락 · LILAC</span></div>'+
    '<div class="head">'+
      '<div><h1>组会工作台</h1><p class="sub" id="listSub">'+listSubText()+'</p></div>'+
      '<div class="hactions">'+
        '<button class="btn ghost" id="eBg" type="button" title="更换首页背景图片">'+IMG_ICON+'背景</button>'+
        (list.length? '<button class="btn" id="eNew">'+PLUS+'新建组会</button>' : '')+
      '</div>'+
    '</div>'+ tools +
    '<div id="listBody">'+listBodyHTML()+'</div>'+
    '<div class="foot"><span class="mark">'+palette(15)+'</span>'+
      '记录保存在本机浏览器中，不会上传。清除浏览器数据会一并清除。</div>'+
  '</div>';
}

/* ---------------- 阅读页 ---------------- */
function readerHTML(m){
  var pk=m.paper.kind||'pdf', sk=m.slides.kind||'pdf';
  return '<div class="reader">'+
    '<div class="rhead">'+
      '<button class="back" id="rBack"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '+
        'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>返回</button>'+
      '<div class="rt">'+esc(m.title)+'</div>'+
      '<div class="rtags">'+tagHTML(m)+'</div>'+
      '<button class="fbtn" id="rRename" type="button" title="改这条组会的名称">改名</button>'+
      '<button class="fbtn" id="rTagEdit" type="button" title="编辑标签">标签</button>'+
      '<div class="rs">'+esc(fmtDate(m.createdAt))+'</div>'+
    '</div>'+
    '<div class="labels">'+
      '<div><b>论文</b><span class="nm">'+esc(m.paper.name)+'</span>'+
        '<b class="tag '+(KINDS[pk]||{}).cls+'">'+kindName(pk)+'</b>'+
        (m.trans?'<span class="seg" id="segView">'+
          '<button type="button" data-view="src"'+(transView?'':' class="on"')+'>原文</button>'+
          '<button type="button" data-view="zh"'+(transView?' class="on"':'')+'>中文</button>'+
        '</span>':'')+
        '<span class="acts">'+
          '<button class="fbtn" type="button" data-open="paper" title="用本机程序打开（浏览器里则下载）">'+OPEN_ICON+'打开</button>'+
          '<button class="fbtn" type="button" data-save="paper" title="另存一份到本机">另存为</button>'+
        '</span></div>'+
      '<div><b>PPT</b><span class="nm">'+esc(m.slides.name)+'</span>'+
        '<b class="tag '+(KINDS[sk]||{}).cls+'">'+kindName(sk)+'</b>'+
        '<span class="acts" id="slidesActs">'+
          (canTextEdit()&&sk==='pptx'?'<button class="fbtn" id="rEdit" type="button" '+
            'title="在右栏打开幻灯片编辑器，改完点「保存并返回」">编辑</button>':'')+
          '<button class="fbtn" id="rSwapSlides" type="button" title="换一份 PPT 替换这一页（会覆盖原文件）">换 PPT</button>'+
          (canTextEdit()&&sk==='pptx'&&(pk==='pdf'||pk==='docx')?'<button class="fbtn" id="rInsImg" type="button" '+
            'title="从论文里挑一张插图，插到当前这一页">插图</button>':'')+
          '<button class="fbtn" type="button" data-open="slides" title="用本机程序打开（浏览器里则下载）">'+OPEN_ICON+'打开</button>'+
          '<button class="fbtn" type="button" data-save="slides" title="另存一份到本机">另存为</button>'+
          '<span class="pager" id="pager" hidden>'+
            '<button id="pgPrev" type="button" aria-label="上一页">‹</button>'+
            '<i id="pgNum">— / —</i>'+
            '<button id="pgNext" type="button" aria-label="下一页">›</button>'+
          '</span>'+
        '</span></div>'+
    '</div>'+
    '<div class="panes">'+
      '<section class="pane"><div class="pbody" id="bodyPaper">'+PANE_LOADING+'</div></section>'+
      '<section class="pane"><div class="pbody" id="bodySlides">'+PANE_LOADING+'</div></section>'+
    '</div>'+
  '</div>';
}
var PANE_LOADING='<div class="loading">正在准备…</div>';

function renderPane(el, rec, isDeck, mid, quiet){
  var kind=rec.kind||'pdf';
  el.innerHTML='<div class="loading">正在载入…</div>';

  if(kind==='pdf'){
    var u=blobURL(rec.blob,'application/pdf');
    el.innerHTML='<iframe class="pending" title="PDF"></iframe>';
    var fr=el.firstChild;
    /* Chromium 内置的 PDF 阅读器会先铺一块深色底，页面真正画好要 500ms 上下，
       而 iframe 的 load 事件在那块深底之前就来了 —— 不能把它当「已经画好了」。
       做法：纸色帘子 + iframe 先透明，等 load 之后再等 480ms，两者交叉淡入。
       用户看到的是「一张纸 + 正在准备…」渐变到论文，而不是一块黑板突然砸下来。 */
    var veil=document.createElement('div');
    veil.className='pveil';
    veil.innerHTML='<div class="loading">正在准备…</div>';
    el.appendChild(veil);
    var lifted=false, lift=function(){
      if(lifted||paneDead(el)) return; lifted=true;
      veil.classList.add('out');
      fr.classList.remove('pending');
      setTimeout(function(){ if(veil.parentNode) veil.parentNode.removeChild(veil); },320);
    };
    if(REDUCED){                           // 减少动效 / 自检：不加帘子，行为与改动前一致
      el.removeChild(veil); fr.classList.remove('pending');
    }else{
      fr.addEventListener('load',function(){ setTimeout(lift,240); });
      setTimeout(lift,1800);               // 兜底：load 万一不来
    }
    fr.src=u;
    return;
  }

  if(kind==='docx'){
    if(typeof window.mammoth==='undefined'){ fail(el,'解析库未加载','请确认这个文件是完整的单文件版本。'); return; }
    rec.blob.arrayBuffer()
      .then(function(buf){return window.mammoth.convertToHtml({arrayBuffer:buf});})
      .then(function(r){
        if(paneDead(el)) return;                 // 收拢中：别往正在退场的栏里画
        el.innerHTML='<article class="docview">'+r.value+'</article>';
        el.scrollTop=0;
      })
      .catch(function(e){ fail(el,'这个 Word 文档打不开',String(e&&e.message||e)); });
    return;
  }

  if(kind==='pptx'){
    if(typeof window.pptxPreview==='undefined'){ fail(el,'解析库未加载','请确认这个文件是完整的单文件版本。'); return; }
    deckInst=null; deckEl=null; deckCount=0; deckIdx=0;   // 别让上一份 deck 的状态留着
    /* ⚠️ 这里必须 return：插完图要「等新的一页真正画好再关弹层」，
       否则弹层关掉的那 200ms 里背后正在重解析 PPT，用户看到的是「页面又闪了一遍」。 */
    return rec.blob.arrayBuffer().then(function(buf){
      if(paneDead(el)) return;                   // 收拢中：别再解析整份 PPT 了
      el.innerHTML='<div class="deckwrap'+(quiet?' quiet':'')+'"><div class="deckstage" id="deckStage">'+
        '<div class="deckhost" id="deckHost"></div></div></div>';
      var host=el.querySelector('#deckHost');
      deckLW=1400; deckLH=Math.round(deckLW*9/16);
      function boot(w,h){
        host.innerHTML='';
        deckInst=window.pptxPreview.init(host,{width:w,height:h,mode:'slide'});
        return deckInst.preview(buf);
      }
      return boot(deckLW,deckLH).then(function(res){
        if(paneDead(el)) return;
        var ratio=(res&&res.height&&res.width)?(res.height/res.width):(9/16);
        var real=Math.round(deckLW*ratio);
        if(Math.abs(real-deckLH)>6){ deckLH=real; return boot(deckLW,deckLH); }
        deckLH=real; return res;
      }).then(function(res){
        if(paneDead(el)) return;                 // 收拢中：连页码/进度都别回写
        deckCount=(res&&res.slides&&res.slides.length)||0;
        deckEl=el; deckIdx=0;
        // 0 页的 pptx 不是「坏文件」，只是里面空的 —— 单独给一句人话，别丢个报错吓人
        if(!deckCount){ fail(el,'这份 PPT 里没有幻灯片', emptyDeckHint(isDeck)); return; }
        fitDeck(); updatePager();
        if(isDeck) $('#pager').hidden = deckCount<2;
        var pr=getProg(mid);                 // 回到上次看到的那一页
        if(pr&&pr.s&&deckCount>1) goSlide(Math.min(pr.s,deckCount-1));
      }).catch(function(e){ pptFail(el,e,isDeck); });
    }).catch(function(e){ pptFail(el,e,isDeck); });
    return;
  }

  fail(el,'这个格式无法在浏览器里预览','');
}

function fail(el,title,detail){
  el.innerHTML='<div class="perr"><div><b>'+esc(title)+'</b>'+
    (detail?'<code>'+esc(detail)+'</code><br>':'')+
    '原始文件已完整保存在本机，可在 WPS / Office 里打开。</div></div>';
}

/* PPT 打不开时给一句人话。
   实测踩到三类失败（2026-10-14）：
     ① 不是有效 zip —— 旧版 .ppt 改名、文件损坏、0 字节、只下了一半；
     ② 是 zip 但一张幻灯片都没有（0 页）→ pptx-preview 抛 reading 'background'；
     ③ 其它解析异常，原样回显。
   ⚠️ 空稿的建议要看在哪一栏：「换 PPT」按钮在右栏，左栏（论文）说这句就是误导。 */
function emptyDeckHint(isDeck){
  return isDeck ? '它是个空稿（0 页）。用「换 PPT」换一份有内容的幻灯片就行。'
                : '它是个空稿（0 页）。左栏只是预览，不影响右边的 PPT。';
}
function pptFail(el,e,isDeck){
  var m=String((e&&e.message)||e||'');
  if(/central directory|is this a zip|Corrupted zip|End of data/i.test(m))
    fail(el,'这不是有效的 .pptx 文件',
      '它可能是旧版 .ppt（请在 WPS / Office 里「另存为」.pptx），或者文件已损坏。');
  else if(/background/i.test(m))
    fail(el,'这份 PPT 里没有幻灯片', emptyDeckHint(isDeck));
  else
    fail(el,'这个 PPT 打不开',m);
}

function fitDeck(){
  if(!deckEl||!deckLW) return;
  var stage=deckEl.querySelector('#deckStage'), host=deckEl.querySelector('#deckHost');
  if(!stage||!host) return;
  var wrap=stage.parentNode;
  var availW=Math.max(200,wrap.clientWidth-32);
  var availH=Math.max(140,wrap.clientHeight-32);
  // 同时适应宽与高：整页幻灯片始终完整可见并居中，不出现滚动条
  var k=Math.max(.05,Math.min(availW/deckLW,availH/deckLH));
  host.style.width=deckLW+'px'; host.style.height=deckLH+'px';
  host.style.transform='scale('+k+')';
  stage.style.width=Math.round(deckLW*k)+'px';
  stage.style.height=Math.round(deckLH*k)+'px';
}
function updatePager(){
  var num=$('#pgNum'); if(!num) return;
  num.textContent=deckCount?((deckIdx+1)+' / '+deckCount):'— / —';
  $('#pgPrev').disabled=deckIdx<=0;
  $('#pgNext').disabled=deckIdx>=deckCount-1;
}
function goSlide(i){
  if(!deckInst||!deckCount) return;
  var prev=deckIdx;
  deckIdx=Math.max(0,Math.min(i,deckCount-1));
  try{ deckInst.renderSingleSlide(deckIdx); }catch(e){}
  /* 翻页是讲组会时最高频的动作，原来换图是瞬时的（硬切）。给一个 220ms 的方向性进场：
     往后翻从右边来、往前翻从左边来 —— 位移只有 14px，但「往哪走」一下就读出来了。 */
  var st=document.querySelector('.deckstage');
  if(st&&!REDUCED&&deckIdx!==prev){
    st.style.setProperty('--sdx',(deckIdx>prev?14:-14)+'px');
    st.classList.remove('slidein');
    void st.offsetWidth;                 // 强制回流，动画才会重放
    st.classList.add('slidein');
  }
  updatePager();
  if(curMid){ var pr=getProg(curMid); pr.s=deckIdx; setProg(curMid,pr); }
}

/* ---------------- 渲染 ---------------- */
/* 左栏：原文预览（PDF / Word / PPT）或中文翻译 */
function paintPaper(m){
  var el=$('#bodyPaper');
  if(!el) return;
  if(transView&&m.trans){
    el.innerHTML='<article class="docview">'+m.trans+'</article>';
    el.scrollTop=0;
    return;
  }
  renderPane(el,m.paper,false,m.id);
}
/* 只重画左栏，不碰右边的 PPT —— 否则切一下就把幻灯片解析和翻页位置全丢了 */
function setTransView(on){
  transView=!!on;
  var m=list.filter(function(x){return x.id===openId;})[0];
  if(!m) return;
  Array.prototype.forEach.call(document.querySelectorAll('#segView button'),function(b){
    b.classList.toggle('on',(b.getAttribute('data-view')==='zh')===transView);
  });
  paintPaper(m);
}

/* ---------------- 换视图：叠加式，不依赖 View Transition ----------------
   ⚠️ 2026-10-17 第二次返工。上一版用 document.startViewTransition，在用户的 WebView2 里
   两次都没看到过渡 —— VT 一旦不可用就退化成「瞬间替换」，于是打开和返回看起来一模一样。
   现在改成纯 DOM + CSS 动画，任何 Chromium 都能跑：
     · 首页 DOM **不销毁**，阅读页以 position:fixed 叠在它上面；
     · 阅读页用 clip-path 从「点击那张卡片的真实矩形」（--rclip）展开，
       裁切之外露出来的是下面真实的首页，不是色块、也不是快照；
     · 返回时反向收拢，收完才 remove()，首页一直在下面原样待着。
   #nomotion / 关动效时仍走整页替换，六套回归的行为与改动前一致。 */
function mountReader(m, quiet){
  var old=document.querySelector('#app .reader');
  /* 同视图重绘（改名、切翻译）不重建：软刷新负责局部更新。
     但「换了幻灯片文件」必须重建 —— 否则界面停在旧内容上（真 bug，2026-10-17 查到）。 */
  if(old&&!quiet) return;
  if(old&&old.parentNode) old.parentNode.removeChild(old);
  var host=document.createElement('div');
  host.innerHTML=readerHTML(m);
  var rd=host.firstElementChild;
  readerLeaving=false;                         // 新阅读页挂上来了，渲染闸重新打开
  var clip=(readerOrigin&&readerOrigin.clip)||'inset(42% 40%)';
  rd.style.setProperty('--rclip',clip);
  lastClip=clip;
  readerOrigin=null;
  $('#app').appendChild(rd);
  if(!quiet){                             // quiet = 用户本来就在这一页，别再来一次展开
    void rd.offsetWidth;                  // 让浏览器先认下起始状态，动画才会从卡片那里开始
    rd.classList.add('opening');
  }
  if(cylRAF){ cancelAnimationFrame(cylRAF); cylRAF=0; }   // 首页在下面，别让它继续转
  revokeAll();
  bindReader(m, rd);
  kickReader(m, rd, quiet);
}

/* 阅读页里所有事件绑在一处：整页替换和叠加两条路径共用 */
function bindReader(m, rd){
  $('#rBack').onclick=function(){ closeReader(); };        // 收拢完才真正离开
  Array.prototype.forEach.call(document.querySelectorAll('#segView button'),function(b){
    b.onclick=function(){ setTransView(b.getAttribute('data-view')==='zh'); };
  });
  $('#pgPrev').onclick=function(){goSlide(deckIdx-1);};
  $('#pgNext').onclick=function(){goSlide(deckIdx+1);};
  $('#rTagEdit').onclick=function(){openTagDialog(m);};
  $('#rRename').onclick=function(){openRenameDlg(m);};
  $('#rSwapSlides').onclick=function(){askReplaceSlides(m);};
  var eb=$('#rEdit'); if(eb) eb.onclick=function(){openEditor(m);};
  var ib=$('#rInsImg'); if(ib) ib.onclick=function(){openPaperImages(m);};
  ['paper','slides'].forEach(function(side){
    var o=$('[data-open="'+side+'"]'), s2=$('[data-save="'+side+'"]');
    if(o) o.onclick=function(){openExtern(m[side]);};
    if(s2) s2.onclick=function(){saveExtern(m[side]);};
  });
}

/* 内容（PDF iframe + 解析整份 PPT）等展开动画落定再上 ——
   一渲染就是几百毫秒的主线程活，同步跑会把动画噎住（实测透明度一步从 0.06 跳到 0.68）。 */
function kickReader(m, rd, quiet){
  var kicked=false, go=function(){
    if(kicked) return; kicked=true;
    if(openId!==m.id) return;
    paintPaper(m);
    renderPane($('#bodySlides'),m.slides,true,m.id);
  };
  if(REDUCED||quiet){ go(); return; }
  var onEnd=function(e){
    if(e.target!==rd) return;             // 只听自己那一条，别被子元素的动画冒泡提前触发
    rd.removeEventListener('animationend',onEnd);   // ⚠️ 用完就摘：不摘的话「收拢」动画结束
                                                    // 时它还会再跑一次（虽然 go() 内部有 openId 守卫，
                                                    // 但这种残留监听器迟早出事）
    rd.classList.remove('opening');       // 动画收尾后撤掉裁剪上下文：常驻的 clip-path
                                          // 会在这一层留下裁剪区域，编辑器 iframe 属于嵌入内容，
                                          // 没必要让它一直待在一个被裁的层里
    go();
  };
  rd.addEventListener('animationend',onEnd);
  setTimeout(go,560);                     // 兜底：动画事件万一不来
}

/* 返回首页：先让阅读页收拢回卡片，收完再移除；首页从头到尾没被动过 */
function closeReader(){
  var rd=document.querySelector('#app .reader');
  readerLeaving=true;                          // 收拢开始：之后所有异步渲染作废
  edFrame=null; edMid=null; edBusy=false;      // iframe 跟着阅读页一起没了，状态别留着
  openId=null; curMid=null;
  revokeAll();
  if(!rd||REDUCED){
    if(rd&&rd.parentNode) rd.parentNode.removeChild(rd);
    render();
    return;
  }
  if(lastClip) rd.style.setProperty('--rclip',lastClip);
  rd.classList.remove('opening');
  void rd.offsetWidth;
  rd.classList.add('closing');
  setTimeout(function(){
    if(rd.parentNode) rd.parentNode.removeChild(rd);
    startCyl();                            // 首页的圆柱接着转
    /* 只有首页真的需要更新（改过名 / 改过标签）时才重建列表。
       插图、翻页不改列表，若也重建，收拢结束后首页会整块重绘一次 —— 那就是「重复一帧」。 */
    if(homeDirty){ homeDirty=false; renderList(true); }
  },380);
}

function render(force){
  edFrame=null; edMid=null; edBusy=false;
  if(openId){
    var m=list.filter(function(x){return x.id===openId;})[0];
    if(m){
      curMid=m.id;
      if(!REDUCED){ mountReader(m, force); return; }
      /* 关动效：整页替换，与改动前完全一致（六套回归走这条）
         ⚠️ 2026-10-17 复查抓到的自伤 bug：closeReader() 会把 readerLeaving 置成 true，
         而**这条分支不走 mountReader**（那里才复位），于是闸一直关着 ——
         表现是「关掉动效后，返回再打开，幻灯片栏永远停在『正在载入…』」。
         实测：第 1 次打开 3048 字符正常，第 2 次只剩 32 字符的占位。 */
      readerLeaving=false;                 // 这条路也要开闸
      $('#app').innerHTML=readerHTML(m);
      revokeAll();
      bindReader(m, document.querySelector('.reader'));
      paintPaper(m);
      renderPane($('#bodySlides'),m.slides,true,m.id);
      return;
    }
    openId=null;
  }
  curMid=null;
  revokeAll();                                   // 离开阅读页：回收上一次的 blob URL
  var stale=document.querySelector('#app .reader');
  if(stale&&stale.parentNode) stale.parentNode.removeChild(stale);
  $('#app').innerHTML=listHTML();
  bindHome();
  startCyl();
}

/* 把卡片矩形变成 clip-path 的 inset 值。
   ⚠️ 必须做能力校验：如果这个字符串在当前内核里不合法，整条 clip-path 声明会被丢弃，
   动画就从「展开」退化成「什么都不发生」。所以三级退让：圆角版 → 方角版 → 固定兜底。 */
function clipFor(rb){
  var W=innerWidth||1, H=innerHeight||1;
  var t=(rb.top/H*100).toFixed(2), r=((W-rb.right)/W*100).toFixed(2);
  var b=((H-rb.bottom)/H*100).toFixed(2), l=(rb.left/W*100).toFixed(2);
  var round='inset('+t+'% '+r+'% '+b+'% '+l+'% round 14px)';
  var plain='inset('+t+'% '+r+'% '+b+'% '+l+'%)';
  try{
    if(window.CSS&&CSS.supports){
      if(CSS.supports('clip-path',round)) return round;
      if(CSS.supports('clip-path',plain)) return plain;
    }
  }catch(e){}
  return 'inset(42% 40%)';
}

/* 首页事件。输入法组字期间绝不重建 DOM，否则中文打不进去（组字会被取消） */
var searchRaf=0;
function bindHome(){
  var n=$('#eNew'); if(n) n.onclick=openDialog;
  var bgBtn=$('#eBg'); if(bgBtn) bgBtn.onclick=openBgDlg;
  var f=$('#fSearch');
  if(f){
    var composing=false;
    var flush=function(){
      if(searchRaf) cancelAnimationFrame(searchRaf);
      searchRaf=requestAnimationFrame(function(){ searchRaf=0; renderList(); });
    };
    /* ⚠️ 必须用 addEventListener：`f.oncompositionstart = fn` 这种属性赋值在 Chromium 里
       挂不上（不是 IDL 事件处理属性），实测派发 compositionstart 时根本不会被调用，
       结果就是中文输入法组字期间照样过滤、组字被打断。 */
    f.addEventListener('compositionstart',function(){ composing=true; });
    f.addEventListener('compositionend',function(){
      composing=false; searchQ=f.value.trim(); flush();
    });
    f.oninput=function(){
      if(composing) return;                      // 组字中，等 compositionend 再刷
      searchQ=f.value.trim();
      flush();
    };
    f.onkeydown=function(e){
      if(e.key==='Escape'){ e.preventDefault(); searchQ=''; f.value=''; flush(); }
    };
  }
  bindChips();
}

/* ---------------- 编辑标签 ---------------- */
function openTagDialog(m){
  tagTarget=m;
  $('#tgInput').value=tagsOf(m).join(' ');
  var ab=$('#tgAuto2');                    // 阅读页里也能自动识别（同样要本机桥）
  if(ab){ var canSug=canSuggestTags(); ab.hidden=!canSug; ab.disabled=!canSug; }
  if(readTagAuto) readTagAuto.reset();
  $('#tagDlg').showModal();
  setTimeout(function(){$('#tgInput').select();},30);
}
function saveTags(){
  if(!tagTarget) return;
  var t=tagTarget; tagTarget=null;
  t.tags=normTags($('#tgInput').value);
  $('#tagDlg').close();
  homeDirty=true;
  // soft：留在阅读页时只更新标签显示 —— 整页重建会重新解析整个 PPT（100~260ms），
  // 只为改几个标签字不值当。记录里的 blob 是 DB 里的句柄，回写不会重拷文件。
  dbPut(t).then(function(){ return refresh({soft:true}); });
}

/* ---------------- 改组会名称 ----------------
   名称存在记录的 title 字段里。改完只替换标题文本，不重建页面 ——
   整页重建会把整个 PPT 重新解析一遍（100~260ms），还把阅读位置退回第一页。 */
var renameTarget=null;
var homeDirty=false;   /* 改名 / 改标签后首页列表要同步；插图、翻页不算 */
function openRenameDlg(m){
  renameTarget=m;
  $('#rnInput').value=m.title||'';
  $('#renameDlg').showModal();
  setTimeout(function(){ var i=$('#rnInput'); i.focus(); i.select(); },30);
}
function saveRename(){
  if(!renameTarget) return;
  var t=renameTarget; renameTarget=null;
  var v=($('#rnInput').value||'').trim();
  $('#renameDlg').close();
  if(!v||v===t.title) return;          // 空名沿用默认规则，清掉则不改
  t.title=v;
  homeDirty=true;
  dbPut(t).then(function(){ return refresh({soft:true}); })
          .catch(function(e){ alert('改名失败：'+e); });
}

/* 「插图」「自动识别标签」这些要在本机干活，只有桌面版有桥；网页版单独打开时不该出现。 */
function canTextEdit(){
  var w=window.pywebview;
  return !!(w&&w.api&&w.api.pptx_read);
}

/* ---------------- 内置幻灯片编辑器（VibeOffice · Lectern，Apache-2.0） ----------------
   在右栏的 iframe 里打开一个真正的 pptx 编辑器，改完点「保存并返回」写回这条记录。
   文档字节走 postMessage：不落盘、不出本机、也不经过任何服务器。
   协议见 编辑器/_zuhui_embed.js（ready / open / opened / saved / cmd）。 */
var edBase=null, edFrame=null, edMid=null, edBusy=false;

function edSay(text){
  var t=document.querySelector('.edbar .edt i');
  if(t) t.textContent=text;
}

function openEditor(m){
  if(edBusy||edFrame) return;
  var pane=$('#bodySlides'); if(!pane) return;
  var w=window.pywebview;
  if(!(w&&w.api&&w.api.editor_base)){ alert('编辑需要桌面版。'); return; }
  edBusy=true; edMid=m.id;
  pane.innerHTML='<div class="edwrap">'+
      '<div class="edbar">'+
        '<span class="edt"><b>编辑幻灯片</b><i>正在打开…</i></span>'+
        '<button class="fbtn" id="edSave" type="button" disabled>保存中…</button>'+
        '<button class="fbtn" id="edQuit" type="button">放弃改动</button>'+
      '</div>'+
      '<div class="edstage" id="edStage"><div class="loading">正在打开编辑器…</div></div>'+
    '</div>';
  var saveBtn=$('#edSave');
  if(saveBtn){ saveBtn.disabled=true; saveBtn.textContent='载入中…'; }
  $('#edQuit').onclick=function(){ closeEditor(m,false); };
  $('#edSave').onclick=function(){ edSaveCmd(); };
  w.api.editor_base().then(function(base){
    if(!base || base.indexOf('err:')===0) throw new Error(String(base||'').replace(/^err:/,''));
    edBase=base;
    var stage=$('#edStage');
    var fr=document.createElement('iframe');
    fr.id='edFrame';
    fr.title='编辑幻灯片';
    fr.src=base+'/lectern/index.html?embed=1';
    fr.addEventListener('load',function(){ if(stage) stage.classList.add('ready'); });
    stage.innerHTML='';
    stage.appendChild(fr);
    edFrame=fr;
  }).catch(function(e){
    edBusy=false;
    var stage=$('#edStage');
    if(stage) stage.innerHTML='<div class="perr">打不开编辑器：'+esc(String((e&&e.message)||e))+'</div>';
    edSay('编辑器不可用');
    setTimeout(function(){ if(!edFrame&&!edBusy) renderPane($('#bodySlides'),m.slides,true,m.id,true); },2400);
  });
}

/* 子页就绪 → 把这一栏的 pptx 交过去 */
function edPushDoc(){
  var m=list.filter(function(x){return x.id===edMid;})[0];
  if(!m||!edFrame||!edFrame.contentWindow) return;
  edSay(m.slides.name);
  var btn=$('#edSave'); if(btn){ btn.disabled=true; btn.textContent='载入中…'; }
  m.slides.blob.arrayBuffer().then(function(buf){
    if(!edFrame) return;
    edFrame.contentWindow.postMessage({__zuhui:'open', name:m.slides.name, bytes:buf}, '*', [buf]);
  });
}

function edSaveCmd(){
  if(!edFrame||!edFrame.contentWindow) return;
  var btn=$('#edSave'); if(btn){ btn.disabled=true; btn.textContent='保存中…'; }
  edSay('正在保存…');
  edFrame.contentWindow.postMessage({__zuhui:'cmd', cmd:'save'}, '*');
}

function edApplySaved(d){
  var m=list.filter(function(x){return x.id===edMid;})[0];
  if(!m){ edSay('保存失败：这条记录已经不在了（可能在别的窗口被删掉）。'); return; }
  /* ⚠️ 2026-10-17 复查查到的数据丢失隐患：原来的判断是 `if(!d.bytes) return`，
     而 **new Uint8Array(0) 是 truthy** —— 编辑器一旦出错回传 0 字节，
     这里会把用户的 PPT 覆盖成空文件、并 dbPut 写进 IndexedDB，**原件就没了**。
     现在拿「PPTX 是 zip，开头必是 PK」当第一道闸：字节为空 / 不是 zip，一律拒绝且不动记录。 */
  var bytes=d&&d.bytes;
  if(bytes&&bytes.byteLength===undefined&&bytes.length!==undefined) bytes=bytes;   // 已是类数组
  else if(bytes instanceof ArrayBuffer) bytes=new Uint8Array(bytes);
  var len=0, magic=false;
  try{ len=(bytes&&(bytes.byteLength||bytes.length))||0; }catch(e){}
  try{ magic=bytes[0]===0x50&&bytes[1]===0x4b; }catch(e){}
  if(!len||!magic){
    edSay('保存失败：编辑器回传的内容不是有效的 PPTX（'+(len||0)+' 字节）。原文件没有被改动。');
    var b=$('#edSave'); if(b){ b.disabled=false; b.textContent='保存并返回'; }
    return;
  }
  edSay('正在写回记录…');
  var type=(m.slides.blob&&m.slides.blob.type)||
    'application/vnd.openxmlformats-officedocument.presentationml.presentation';
  /* 先留旧值：写库失败要能把内存里的改动退回去，否则界面显示新的、库里还是旧的 */
  var oldBlob=m.slides.blob, oldSize=m.slides.size, oldRev=m.slides.rev;
  m.slides.blob=new Blob([bytes],{type:type});
  m.slides.size=len;
  m.slides.rev=(m.slides.rev||0)+1;      // 内容变了，版本号 +1
  homeDirty=true;                        // 首页卡片上的「大小」等信息要跟着更新
  dbPut(m).then(function(){ closeEditor(m,true); })
          .catch(function(e){
            m.slides.blob=oldBlob; m.slides.size=oldSize; m.slides.rev=oldRev;
            homeDirty=false;
            edSay('保存失败：写入记录出错（'+e+'）。已回滚，原文件没有被改动。');
            var b2=$('#edSave'); if(b2){ b2.disabled=false; b2.textContent='保存并返回'; }
          });
}

function closeEditor(m,saved){
  var fr=edFrame;
  edFrame=null; edMid=null; edBusy=false;
  var stage=$('#edStage');
  if(fr&&fr.parentNode&&stage&&!saved){
    stage.classList.remove('ready');     // 先淡出再抽走，别硬切
  }
  var pane=$('#bodySlides');
  if(pane&&m) renderPane(pane, m.slides, true, m.id, true);
  if(saved&&homeDirty){ homeDirty=false; renderList(true); }
}

/* 编辑器回传：只认我们自己那个 iframe 的消息 */
window.addEventListener('message',function(ev){
  var d=ev.data||{};
  if(!d.__zuhui) return;
  if(edFrame&&ev.source!==edFrame.contentWindow) return;
  if(d.__zuhui==='ready'){ edPushDoc(); }
  else if(d.__zuhui==='opened'){
    var btn=$('#edSave'); if(btn){ btn.disabled=false; btn.textContent='保存并返回'; }
  }
  else if(d.__zuhui==='saved'){ edApplySaved(d); }
  else if(d.__zuhui==='error'){ edSay('出错：'+String(d.error||'')); }
});

/* ---------------- 从论文里挑一张插图插到当前页 ----------------
   只有一条路：**按页框选** —— 整页渲染出来，拖个框，插进去的就是你框的那块。
   为什么不做「抽内嵌位图」那条路：PDF 里一张多子图 Figure 常由**多个位图对象**拼成
   （实测 arXiv-1905.02315 的 Figure 3 就是 6 个独立对象，尺寸还几乎一样），
   直接抽对象只能拿到碎片，插进幻灯片自然「四分五裂」；而且纯矢量画的图根本抽不到。
   渲染整页再框选没有这两个毛病。
   插入用 python-pptx 的 add_picture，等比缩放到版心内、水平居中。 */
var imgPage=0, imgSel=null, imgDrag=null, imgM=null;
/* ⚠️ 2026-10-17 复查抓到的 bug：点「插入」之后立刻点 ×，**图还是插进去了**
   （实测 rev 1→2、9 字节 → 1MB）。插入是几秒的异步链，关弹层打断不了它。
   加任务代号：开弹层 / 关弹层都 +1，异步链每段比对，代号变了整条作废。 */
var imgJob=0;

function openPaperImages(m){
  var w=window.pywebview;
  if(!(w&&w.api&&w.api.paper_pages)){ alert('插图功能需要桌面版。'); return; }
  imgJob++;                                   // 新一轮：作废上一轮没走完的链
  imgM=m; imgPage=0; imgSel=null; imgDrag=null;
  if(!$('#imgDlg').open) $('#imgDlg').showModal();
  loadPageThumbs(m);
}

/* —— 按页框选 —— */
function loadPageThumbs(m){
  var w=window.pywebview, box=$('#imThumbs'), hint=$('#imHint');
  if(!(w&&w.api&&w.api.paper_pages)){
    box.innerHTML=''; $('#imStage').hidden=true;
    hint.textContent='这个版本不支持按页框选，请更新到新版。'; return;
  }
  if((m.paper.kind||'pdf')!=='pdf'){
    box.innerHTML=''; $('#imStage').hidden=true;
    hint.textContent='插图靠「渲染论文页 + 框选」，只有 PDF 能做。'
      + '这份是 Word —— 请在 Word 里「另存为 PDF」后重新导入，或在 Word 里自己截图。';
    return;
  }
  $('#imStage').hidden=false;
  box.innerHTML=''; $('#imPageImg').removeAttribute('src');
  hint.textContent='正在渲染论文页…';
  fileToBase64(m.paper.blob).then(function(b64){
    return w.api.paper_pages(b64, 'pdf', 40);
  }).then(function(raw){
    var r={}; try{ r=JSON.parse(raw); }catch(e){}
    if(!r.ok) throw new Error(r.error||'渲染失败');
    if(!r.pages||!r.pages.length){ hint.textContent='这份 PDF 读不出页面。'; return; }
    r.pages.forEach(function(p){
      var b=document.createElement('button');
      b.type='button'; b.className='imthumb'; b.setAttribute('data-i', p.i);
      b.innerHTML='<img alt=""><i>'+(p.i+1)+'</i>';
      b.querySelector('img').src='data:image/jpeg;base64,'+p.b64;
      b.onclick=function(){ showPage(p.i); };
      box.appendChild(b);
    });
    hint.textContent='选一页，在页面上拖一个框框住你要的那张图，再点「插入选中区域」。'
      + (r.total>r.shown ? '（共 '+r.total+' 页，只列出前 '+r.shown+' 页）' : '');
    showPage(0);
  }).catch(function(e){ hint.textContent='渲染失败：'+e; });
}

function showPage(i){
  var m=imgM, w=window.pywebview, hint=$('#imHint');
  imgPage=i; imgSel=null; imgDrag=null;
  $('#imSel').hidden=true; $('#imSize').textContent='';
  Array.prototype.forEach.call(document.querySelectorAll('#imThumbs .imthumb'),function(b){
    b.classList.toggle('on', +b.getAttribute('data-i')===i);
  });
  fileToBase64(m.paper.blob).then(function(b64){
    return w.api.paper_page_crop(b64, 'pdf', i, 0, 0, 1, 1, 1400, 'jpeg');   // 整页当预览
  }).then(function(raw){
    var r={}; try{ r=JSON.parse(raw); }catch(e){}
    if(!r.ok) throw new Error(r.error||'取页失败');
    var img=$('#imPageImg');
    img.onload=function(){
      // ⚠️ 默认就把**整页**框出来，让「框可以拖」这件事看得见。
      //    以前默认没有选区、按钮又叫「插入选中区域」，用户不拖框就直接点，
      //    插进去当然是整页 —— 表现就是「每次都插一整张图」。
      var st=$('#imStage'), rr=st.getBoundingClientRect();
      imgSel={x0:0, y0:0, x1:rr.width, y1:rr.height};
      paintImgSel();
    };
    img.src='data:image/jpeg;base64,'+r.b64;
  }).catch(function(e){ hint.textContent='取页失败：'+e; });
}

/* 画选区 + 让按钮自己说清楚「会插入什么」 */
function paintImgSel(){
  var stage=$('#imStage'), sel=$('#imSel'), size=$('#imSize'), btn=$('#imInsert');
  if(!stage||!sel) return;
  var r=stage.getBoundingClientRect();
  if(!imgSel || !r.width){
    sel.hidden=true;
    if(size) size.textContent='没框选 → 会插入整页';
    if(btn) btn.textContent='插入整页';
    return;
  }
  sel.hidden=false;
  sel.style.left=imgSel.x0+'px'; sel.style.top=imgSel.y0+'px';
  sel.style.width=(imgSel.x1-imgSel.x0)+'px'; sel.style.height=(imgSel.y1-imgSel.y0)+'px';
  var pw=Math.round((imgSel.x1-imgSel.x0)/r.width*100);
  var ph=Math.round((imgSel.y1-imgSel.y0)/r.height*100);
  var whole = pw>=97 && ph>=97;
  if(size) size.textContent = whole ? '当前框的是整页 —— 在页面上拖一下可以缩小'
                                    : ('已框选 '+pw+'% × '+ph+'%');
  if(btn) btn.textContent = whole ? '插入整页' : '插入选中区域';
}

function bindImgCrop(){
  var stage=$('#imStage');
  if(!stage) return;
  function local(cx,cy){
    var r=stage.getBoundingClientRect();
    return {x:Math.min(Math.max(cx-r.left,0), r.width),
            y:Math.min(Math.max(cy-r.top,0), r.height)};
  }
  function start(cx,cy){
    var img=$('#imPageImg');
    if(!img || !img.naturalWidth) return false;
    var p=local(cx,cy); imgDrag={x:p.x, y:p.y};
    imgSel={x0:p.x, y0:p.y, x1:p.x, y1:p.y};
    paintImgSel();
    return true;
  }
  function move(cx,cy){
    if(!imgDrag) return;
    var p=local(cx,cy);
    imgSel={x0:Math.min(imgDrag.x,p.x), y0:Math.min(imgDrag.y,p.y),
            x1:Math.max(imgDrag.x,p.x), y1:Math.max(imgDrag.y,p.y)};
    paintImgSel();
  }
  function done(){
    if(!imgDrag) return;
    imgDrag=null;
    if(imgSel && ((imgSel.x1-imgSel.x0)<6 || (imgSel.y1-imgSel.y0)<6)) imgSel=null;  // 手抖＝没框
    paintImgSel();
  }
  // pointer 事件为主，鼠标事件兜底 —— WebView2 上 setPointerCapture 偶有不生效，
  // 只挂 pointer 的话拖框会静默失灵（表现同样是「插进去是整页」）。
  stage.addEventListener('pointerdown',function(e){
    if(start(e.clientX,e.clientY)){ e.preventDefault();
      try{ stage.setPointerCapture(e.pointerId); }catch(err){} }
  });
  stage.addEventListener('pointermove',function(e){ move(e.clientX,e.clientY); });
  stage.addEventListener('pointerup',done);
  stage.addEventListener('pointercancel',done);
  stage.addEventListener('mousedown',function(e){
    if(imgDrag) return;                       // pointer 已经接管，别重复起手
    if(start(e.clientX,e.clientY)) e.preventDefault();
  });
  // 移动 / 抬起挂到 window 上：就算指针跑到弹层外面，拖框也不会断
  window.addEventListener('mousemove',function(e){ if(imgDrag) move(e.clientX,e.clientY); });
  window.addEventListener('mouseup',done);
  $('#imClear').onclick=function(){ imgSel=null; paintImgSel(); };
  $('#imInsert').onclick=insertImgRegion;
}

function insertImgRegion(){
  var m=imgM, w=window.pywebview, hint=$('#imHint');
  if(!m||!w) return;
  var stage=$('#imStage'), r=stage.getBoundingClientRect();
  var f = (imgSel && r.width) ? {x:imgSel.x0/r.width, y:imgSel.y0/r.height,
                                 w:(imgSel.x1-imgSel.x0)/r.width,
                                 h:(imgSel.y1-imgSel.y0)/r.height}
                               : {x:0, y:0, w:1, h:1};
  var job=imgJob;                             // 本次任务代号
  $('#imInsert').disabled=true;
  hint.textContent='正在渲染这一块…';
  fileToBase64(m.paper.blob).then(function(pb){
    return w.api.paper_page_crop(pb, 'pdf', imgPage, f.x, f.y, f.w, f.h, 2400, 'png');
  }).then(function(raw){
    if(job!==imgJob) return null;             // 弹层已关 → 绝不改记录
    var r2={}; try{ r2=JSON.parse(raw); }catch(e){}
    if(!r2.ok) throw new Error(r2.error||'渲染失败');
    hint.textContent='正在插入到第 '+(deckIdx+1)+' 页…';
    return addImageToSlide(m, r2.b64);
  }).then(function(){
    if(job!==imgJob) return;                  // 已取消：不用再关弹层
    closeDlgNow($('#imgDlg'));
  }).catch(function(e){
    if(job!==imgJob) return;
    hint.textContent='插入失败：'+e;
  }).then(function(){ if(job===imgJob) $('#imInsert').disabled=false; });
}

/* 把一张图的字节插到当前页 */
function addImageToSlide(m, imgB64){
  var w=window.pywebview;
  return fileToBase64(m.slides.blob).then(function(sb){
    return w.api.pptx_add_image(sb, deckIdx, imgB64);
  }).then(function(raw2){
    var r2={}; try{ r2=JSON.parse(raw2); }catch(e){}
    if(!r2.ok) throw new Error(r2.error||'插入失败');
    var bin=atob(r2.b64), arr=new Uint8Array(bin.length);
    for(var i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
    m.slides.blob=new Blob([arr],{type:m.slides.blob.type||''});
    m.slides.size=r2.size;
    m.slides.rev=(m.slides.rev||0)+1;              // 内容变了，版本号 +1（换过几次这一栏的内容）
    return dbPut(m).then(function(){
      // quiet：插图只改了这一页的内容，画面本来就在，不该再播一次「落进来」的进场动画
      return renderPane($('#bodySlides'), m.slides, true, m.id, true);
    });
  });
}

/* ---------------- 替换 PPT ----------------
   PPT 常会改好几版，允许在阅读页直接换掉，不必重建整条组会记录。 */
function askReplaceSlides(m){
  swapTarget=m;
  var inp=$('#pickReplace');
  inp.value='';
  inp.click();
}
function replaceSlides(m,f){
  swapTarget=null;
  if(!m||!f) return;
  var kind=kindOf(f.name);
  if(kind==='legacy-doc'||kind==='legacy-ppt'){
    alert('这是旧版格式，请在 WPS / Office 里另存为 '+
      (kind==='legacy-doc'?'.docx 或 PDF':'.pptx 或 PDF'));
    return;
  }
  if(!kind){ alert('只支持 PDF、Word（.docx）、PPT（.pptx）'); return; }
  // rev+1：同名同大小的另一份文件也要能被认出来，不能命中旧缓存
  m.slides={name:f.name,size:f.size,kind:kind,blob:f,rev:((m.slides&&m.slides.rev)||0)+1};
  dbPut(m).then(function(){
    var pr=getProg(m.id);              // 换了 PPT，之前记的页码作废
    if(pr&&pr.s!==undefined){ delete pr.s; setProg(m.id,pr); }
    return refresh();
  }).catch(function(e){ alert('替换失败：'+e); });
}

/* ---------------- 新建弹层 ---------------- */
function openDialog(){
  pending={paper:null,slides:null}; slotErr={};
  $('#fTitle').value=defaultTitle();
  $('#fTags').value='';
  paintSlots();
  $('#dlg').showModal();
  setTimeout(function(){$('#fTitle').select();},30);
}
function paintSlots(){
  [['#slotPaper','paper','论文文件'],['#slotSlides','slides','PPT 文件']].forEach(function(cfg){
    var el=$(cfg[0]), p=pending[cfg[1]], html='';
    el.classList.toggle('done',!!p);
    if(p){
      var k=KINDS[p.kind]||{tag:'—',cls:''};
      html='<div class="si"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '+
        'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>'+
        '<div class="sk">'+cfg[2]+'</div>'+
        '<div class="sn">'+esc(p.file.name)+'</div>'+
        '<div class="ss">'+k.tag+' · '+fmtSize(p.file.size)+'</div>';
    }else{
      html=slotDefault[cfg[1]];
    }
    if(slotErr[cfg[1]]) html+='<div class="err">'+esc(slotErr[cfg[1]])+'</div>';
    el.innerHTML=html;
  });
  $('#dSave').disabled=!(pending.paper&&pending.slides);
  var ab=$('#tgAuto');
  if(ab){
    // 浏览器里没有本机桥，识别不了（要读文件、跑分词），按钮点了也是空的 —— 干脆不显示
    var canSug=canSuggestTags();
    ab.hidden=!canSug;
    ab.disabled=!canSug||!pending.paper;   // 只要论文就能识别，PPT 可以还没选
  }
  // 换了文件，上一次的识别结果就不作数了，收起来；要看得再点一次「自动识别标签」
  if(newTagAuto) newTagAuto.reset();
}

/* ---------------- 自动识别标签（新建弹层 + 阅读页共用） ----------------
   点按钮才跑（不自动跑 —— 免得你还没选完文件它就乱跳）：
   后端从论文 / PPT 正文里猜标签：① 优先给出用户**以前用过**的（标「用过」），
   保持标签体系一致；② 其余是自动发现的新词。**只出中文**（英文术语在
   后端就折成中文了）。前 3 个自动填进标签框，点 chip 可加/去掉，也能直接手打。
   两处入口（新建组会 / 阅读页「标签」弹层）共用同一套逻辑，只是取文件的方式不同。 */
function allKnownTags(){
  var seen={}, out=[];
  list.forEach(function(mm){
    tagsOf(mm).forEach(function(t){ if(!seen[t]){seen[t]=1; out.push(t);} });
  });
  return out;
}
function setTagChipIn(inp,btn,tag,on){
  var cur=normTags(inp.value);
  if(on){ if(cur.indexOf(tag)<0) cur.push(tag); btn.classList.add('on'); }
  else  { cur=cur.filter(function(x){return x!==tag;}); btn.classList.remove('on'); }
  inp.value=cur.slice(0,8).join(' ');
}
function syncTagChipsIn(inp,chipsEl){             // 手改标签框后，chip 状态跟着走
  if(!chipsEl) return;
  var cur=normTags(inp.value);
  Array.prototype.forEach.call(chipsEl.querySelectorAll('.tgchip'),function(b){
    b.classList.toggle('on', cur.indexOf(b.getAttribute('data-tag'))>=0);
  });
}
/* ui={inp,box,chips,txt}；getFiles() 返回 {paperFile,paperKind,slidesFile,slidesKind} 或 null */
function makeTagAuto(ui,getFiles){
  var token=0;
  function reset(){ token++; if(ui.box) ui.box.hidden=true; if(ui.chips) ui.chips.innerHTML=''; }
  function run(){
    var w=window.pywebview;
    if(!(w&&w.api&&w.api.suggest_tags)){ if(ui.box) ui.box.hidden=true; return; }
    var fs=null; try{ fs=getFiles(); }catch(e){ fs=null; }
    var t=++token;
    ui.box.hidden=false; ui.chips.innerHTML='';
    if(!fs){ ui.txt.textContent='先把论文选上（PPT 可以后面再补）。'; return; }
    ui.txt.textContent = fs.slidesFile ? '正在从论文和 PPT 里识别标签…' : '正在从论文里识别标签…';
    var known=allKnownTags();
    var pName=(fs.paperFile&&fs.paperFile.name)||'';
    var sName=(fs.slidesFile&&fs.slidesFile.name)||'';
    fileToBase64(fs.paperFile).then(function(pb){
      // 没有 PPT 就只传论文 —— 标签本来就主要看论文
      if(!fs.slidesFile) return w.api.suggest_tags(pb, fs.paperKind, '', '',
                                                   JSON.stringify(known), pName);
      return fileToBase64(fs.slidesFile).then(function(sb){
        return w.api.suggest_tags(pb, fs.paperKind, sb, fs.slidesKind,
          JSON.stringify(known), pName+' '+sName);
      });
    }).then(function(raw){
      if(t!==token) return;                      // 又换了文件 / 关了弹层，这次结果作废
      var r={}; try{ r=JSON.parse(raw); }catch(e){}
      var items=r.items||[];
      if(!items.length){
        // 后端会说明原因（扫描件？文件没下完整？方向不在词表里？后端报错？）
        // —— 别让用户只看到「什么都没发生」，那会被当成功能坏了。
        var why = r.reason || (r.ok===false ? ('识别出错：'+(r.error||'未知原因')) : '');
        if(why){ ui.box.hidden=false; ui.chips.innerHTML=''; ui.txt.textContent=why; }
        else { ui.box.hidden=true; }
        return;
      }
      ui.txt.textContent='识别到这些标签（点一下加/去掉）：';
      items.forEach(function(it,i){
        var b=document.createElement('button');
        b.type='button'; b.className='tgchip'; b.setAttribute('data-tag',it.tag);
        b.innerHTML=esc(it.tag)+(it.known?'<em>用过</em>':'');
        b.onclick=function(){ setTagChipIn(ui.inp,b,it.tag,!b.classList.contains('on')); };
        ui.chips.appendChild(b);
        if(i<3) setTagChipIn(ui.inp,b,it.tag,true);   // 前 3 个自动填上
      });
    }).catch(function(e){
      if(t!==token) return;
      ui.box.hidden=false; ui.chips.innerHTML='';
      ui.txt.textContent='识别失败：'+(e&&e.message?e.message:e);
    });
  }
  return {run:run, reset:reset, sync:function(){ syncTagChipsIn(ui.inp,ui.chips); }};
}
var newTagAuto=null, readTagAuto=null;
function canSuggestTags(){
  var w=window.pywebview;
  return !!(w&&w.api&&w.api.suggest_tags);
}
function bindTagAuto(){
  var dInp=$('#fTags'), rInp=$('#tgInput');
  if(dInp) newTagAuto=makeTagAuto(
    {inp:dInp, box:$('#tgSug'), chips:$('#tgChips'), txt:$('#tgSugTxt')},
    function(){
      if(!pending.paper) return null;         // 论文是必需的，PPT 可有可无
      return {paperFile:pending.paper.file, paperKind:pending.paper.kind,
              slidesFile: pending.slides ? pending.slides.file : null,
              slidesKind: pending.slides ? pending.slides.kind : ''};
    });
  if(rInp) readTagAuto=makeTagAuto(
    {inp:rInp, box:$('#tgSug2'), chips:$('#tgChips2'), txt:$('#tgSugTxt2')},
    function(){
      var m=tagTarget;
      if(!m||!m.paper) return null;           // 同上：没 PPT 也能识别
      return {paperFile:m.paper.blob, paperKind:m.paper.kind||'pdf',
              slidesFile: m.slides ? m.slides.blob : null,
              slidesKind: m.slides ? (m.slides.kind||'pdf') : ''};
    });
  if($('#tgAuto'))  $('#tgAuto').onclick=function(){ if(newTagAuto) newTagAuto.run(); };
  if($('#tgAuto2')) $('#tgAuto2').onclick=function(){ if(readTagAuto) readTagAuto.run(); };
  if(dInp) dInp.addEventListener('input',function(){ if(newTagAuto) newTagAuto.sync(); });
  if(rInp) rInp.addEventListener('input',function(){ if(readTagAuto) readTagAuto.sync(); });
}
function takeFile(side,f){
  if(!f) return;
  var kind=kindOf(f.name);
  if(kind==='legacy-doc'||kind==='legacy-ppt'){
    slotErr[side]='这是旧版格式，请在 WPS / Office 里「另存为」'+
      (kind==='legacy-doc'?' .docx 或 PDF':' .pptx 或 PDF');
    paintSlots(); return;
  }
  if(!kind){
    slotErr[side]='只支持 PDF、Word（.docx）、PPT（.pptx）';
    paintSlots(); return;
  }
  slotErr[side]='';
  var replacing = (side==='paper' && pending.paper);
  pending[side]={file:f,kind:kind};
  paintSlots();
  // 论文一选好就自动识别标签 —— 标签只看论文，不用等 PPT 选完再点按钮。
  // 换论文时先把上一次自动填进去的标签清掉（那些是从旧论文来的）。
  if(side==='paper' && newTagAuto){
    if(replacing){ var ti=$('#fTags'); if(ti) ti.value=''; }
    newTagAuto.run();
  }
}

/* ---------------- 事件 ---------------- */
function bindGlobal(){
  $('#dClose').onclick=function(){$('#dlg').close();};
  $('#dCancel').onclick=function(){$('#dlg').close();};
  $('#dSave').onclick=saveMeeting;
  $('#tgClose').onclick=function(){$('#tagDlg').close();};
  $('#tgCancel').onclick=function(){$('#tagDlg').close();};
  $('#tgSave').onclick=saveTags;
  $('#rnClose').onclick=function(){$('#renameDlg').close();};
  $('#rnCancel').onclick=function(){$('#renameDlg').close();};
  $('#rnSave').onclick=saveRename;
  bindTagAuto();                             // 新建弹层 + 阅读页标签弹层共用
  /* 关弹层一律作废在途任务，否则「取消」其实没取消（见 imgJob 注释） */
  $('#imClose').onclick=function(){ imgJob++; closeDlgNow($('#imgDlg')); };
  $('#imCancel').onclick=function(){ imgJob++; closeDlgNow($('#imgDlg')); };
  bindImgCrop();
  $('#tgInput').addEventListener('keydown',function(e){
    if(e.key==='Enter'){e.preventDefault();saveTags();}
  });
  $('#rnInput').addEventListener('keydown',function(e){
    if(e.key==='Enter'){e.preventDefault();saveRename();}
  });

  /* 背景图：选择 / 恢复默认 */
  $('#bgClose').onclick=function(){$('#bgDlg').close();};
  $('#bgDone').onclick=function(){$('#bgDlg').close();};
  $('#bgRows').addEventListener('click',function(e){
    var b=e.target.closest('button[data-act]'); if(!b) return;
    var row=e.target.closest('.bgrow'); if(!row) return;
    var k=row.getAttribute('data-slot');
    if(b.getAttribute('data-act')==='pick'){
      bgPickSlot=k; $('#pickBg').value=''; $('#pickBg').click();
    }else{
      setDel('bg.'+k).then(function(){ bgSet(k,null); paintBgRows(); })
        .catch(function(err){ alert('恢复失败：'+((err&&err.message)||err)); });
    }
  });
  $('#pickBg').addEventListener('change',function(){
    var f=this.files&&this.files[0]; if(!f||!bgPickSlot) return;
    var k=bgPickSlot; bgPickSlot=null;
    if(!/^image\//.test(f.type)){ alert('请选择图片文件（jpg / png / webp 等）'); return; }
    setPut('bg.'+k,f).then(function(){ bgSet(k,f); paintBgRows(); })
      .catch(function(err){ alert('保存失败：'+((err&&err.message)||err)); });
  });

  [['#slotPaper','paper','#pickPaper'],['#slotSlides','slides','#pickSlides']].forEach(function(cfg){
    var el=$(cfg[0]), input=$(cfg[2]);
    slotDefault[cfg[1]]=el.innerHTML;
    el.addEventListener('click',function(){input.click();});
    el.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();input.click();}});
    el.addEventListener('dragover',function(e){e.preventDefault();el.classList.add('over');});
    el.addEventListener('dragleave',function(){el.classList.remove('over');});
    el.addEventListener('drop',function(e){
      e.preventDefault(); el.classList.remove('over');
      var f=e.dataTransfer.files&&e.dataTransfer.files[0];
      takeFile(cfg[1],f);
    });
    input.addEventListener('change',function(){takeFile(cfg[1],input.files[0]);input.value='';});
  });

  $('#pickReplace').addEventListener('change',function(){
    var f=this.files&&this.files[0]; this.value='';
    replaceSlides(swapTarget,f);
  });

  window.addEventListener('dragover',function(e){e.preventDefault();});
  window.addEventListener('drop',function(e){e.preventDefault();});
  /* resize 会连发几十次，用 rAF 收口，避免每次事件都读布局 */
  var fitRaf=0;
  window.addEventListener('resize',function(){
    if(fitRaf) return;
    fitRaf=requestAnimationFrame(function(){ fitRaf=0; fitDeck(); });
  });

  /* 首页圆柱：拖动旋转（鼠标 / 触屏） */
  document.addEventListener('pointerdown',function(e){
    cylMoved=0;                                        // 任何按下都清零：否则上一次拖动会吞掉这次点击
    var g=e.target.closest('.group'); if(!g||!g.querySelector('.cyl')) return;
    cylDragging=true; cylLastX=e.clientX; cylPauseUntil=0;
    g.classList.add('dragging');
    /* ⚠️ 不要 setPointerCapture：它会把后续 click 重定向到 .group，
       于是 e.target.closest('.row') 找不到卡片，点卡片打不开。 */
  });
  document.addEventListener('pointermove',function(e){
    if(!cylDragging) return;
    var now=performance.now();
    var dx=e.clientX-cylLastX; cylLastX=e.clientX; cylMoved+=Math.abs(dx);
    var d=dx*0.32; cylRot+=d;
    var dtm=Math.max(1,now-(cylLastT||now-16)); cylLastT=now; cylLastMoveT=now;
    cylVel=Math.max(-1.1,Math.min(1.1,d/dtm));   // 度/毫秒，限幅防「一甩飞出去」
    cylSpin=false;                               // 还在拖 → 先关掉滑行
    cylApply();
  });
  function endCylDrag(){
    if(!cylDragging) return;
    cylDragging=false; cylLastT=0; cylPauseUntil=performance.now()+900;
    /* 松手时才有惯性：手停住了（>110ms 没动）就当作「放稳了」，不要自己滑。 */
    var moving=performance.now()-cylLastMoveT<110;
    cylSpin=!REDUCED&&moving&&Math.abs(cylVel)>0.05;
    if(!cylSpin) cylVel=0;
    var g=document.querySelector('.group.dragging'); if(g) g.classList.remove('dragging');
  }
  document.addEventListener('pointerup',endCylDrag);
  document.addEventListener('pointercancel',endCylDrag);
  window.addEventListener('blur',endCylDrag);          // 拖动中切走窗口收不到 pointerup → 兜底解除

  document.addEventListener('keydown',function(e){
    if(!openId||!deckCount) return;
    if(document.querySelector('dialog[open]')) return;   // 弹层开着时别翻底下的 PPT
    var t=(e.target.tagName||'').toLowerCase();
    if(t==='input'||t==='textarea') return;
    if(e.key==='ArrowRight'||e.key==='PageDown'){e.preventDefault();goSlide(deckIdx+1);}
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();goSlide(deckIdx-1);}
  });

  $('#app').addEventListener('click',function(e){
    if(cylMoved>6){ cylMoved=0; return; }        // 刚才是拖动，不当点击
    /* 筛选栏的「⋯ +N」：切换展开/收起。放在最前面 ——
       它不在 .row 里，落到下面那个分支会因为取不到 row 而报错。 */
    if(e.target.closest('[data-tagmore]')){
      tagsOpen=!tagsOpen; paintChips(); return;
    }
    var act=e.target.closest('[data-act]');
    if(act){
      var row=act.closest('.row'), id=row.getAttribute('data-id');
      if(act.getAttribute('data-act')==='rm'){confirming=id;render();}
      else if(act.getAttribute('data-act')==='cancel'){confirming=null;render();}
      else if(act.getAttribute('data-act')==='drop'){
        dbDel(id).then(function(){confirming=null;return refresh();});
      }
      return;
    }
    var r=e.target.closest('.row');
    if(r){
      /* 记下落点：阅读页从这张卡片的**矩形**拉开成整页，而不是整屏淡入。
         空间关系本身就是解释 —— 从哪来、到哪去，用户不用猜。
         （纯透明度过渡人眼几乎察觉不到，这是 2026-10-17 实测「感觉没改」的主因。） */
      var rb=r.getBoundingClientRect();
      var W=innerWidth, Hh=innerHeight;
      readerOrigin={ox:((rb.left+rb.width/2)/W*100).toFixed(2)+'%',
                    oy:((rb.top+rb.height/2)/Hh*100).toFixed(2)+'%',
                    clip:clipFor(rb)};
      openId=r.getAttribute('data-id');transView=false;render();
    }
  });
}

function saveMeeting(){
  var title=($('#fTitle').value||'').trim()||defaultTitle();
  var m={
    id:'m'+Date.now()+Math.random().toString(36).slice(2,7),
    title:title, createdAt:Date.now(), tags:normTags($('#fTags').value),
    paper:{name:pending.paper.file.name,size:pending.paper.file.size,
           kind:pending.paper.kind,blob:pending.paper.file},
    slides:{name:pending.slides.file.name,size:pending.slides.file.size,
            kind:pending.slides.kind,blob:pending.slides.file,rev:1}
  };
  $('#dSave').disabled=true;
  dbPut(m).then(function(){
    $('#dlg').close();
    return refresh();
  }).then(function(){openId=m.id;transView=false;render();}).catch(function(err){
    alert('保存失败：'+err);
    $('#dSave').disabled=false;
  });
}

function refresh(opts){
  return dbAll().then(function(rows){
    list=rows.sort(function(a,b){return b.createdAt-a.createdAt;});
    list.forEach(function(m){
      if(m.paper&&!m.paper.kind) m.paper.kind='pdf';
      if(m.slides&&!m.slides.kind) m.slides.kind='pdf';
    });
    if(opts&&opts.soft&&openId){
      var m=list.filter(function(x){return x.id===openId;})[0];
      if(!m) return;
      var box=document.querySelector('.rtags');
      if(box) box.innerHTML=tagHTML(m);
      var tt=document.querySelector('.rt');        // 改名后同步标题
      if(tt) tt.textContent=m.title;
      return;
    }
    render(!!openId);        // 阅读页里刷新（换幻灯片等）要强制重建；首页照旧
  });
}

/* ---------------- 启动 ---------------- */
function boot(){
  bindGlobal();
  openDB().then(function(d){ db=d; return bgLoadAll(); })
   .then(function(){ return refresh(); })
   .catch(function(err){
     $('#app').innerHTML='<div class="wrap"><div class="empty"><div class="et">无法读取本机存储</div>'+
       '<p class="es">'+esc(err&&err.message||err)+'</p></div></div>';
   });
}
/* ---------------- 网页版：连本机上开着的 exe ----------------
   exe 启动时会在 127.0.0.1 上开一个本机接口。用浏览器打开这个页面时先探一下：
   探到了就把 window.pywebview 伪造出来，页面照常工作 —— 编辑 / 插图 / 识别标签
   全都能用，跟 exe 里一样；探不到就退回基础功能（相关按钮自动隐藏）。

   桌面版有真的桥，走 pywebviewready 事件立刻放行，**不会多等**。 */
var BRIDGE_METHODS=['editor_base',
  'suggest_tags','paper_pages','paper_page_crop','pptx_add_image',
  'pptx_read','pptx_write','open_file'];
function bridgeProbe(done){
  var settled=false;
  function settle(){ if(settled) return; settled=true; done(); }
  if(window.pywebview&&window.pywebview.api) return settle();
  window.addEventListener('pywebviewready', settle);      // 桌面版：桥好了立刻走
  var timer=setTimeout(settle, 900);                      // 兜底，别让页面卡住

  var ports=[], p;
  for(p=39177;p<39187;p++) ports.push(p);
  var port=0, left=ports.length;
  function call(method,args){
    return fetch('http://127.0.0.1:'+port+'/call',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({method:method,args:args})
    }).then(function(r){
      if(!r.ok) throw new Error('本机程序返回 '+r.status);
      return r.json();
    }).then(function(j){
      if(!j||!j.ok) throw new Error((j&&j.error)||'调用失败');
      return j.result;
    });
  }
  ports.forEach(function(pp){
    fetch('http://127.0.0.1:'+pp+'/ping').then(function(r){ return r.json(); }).then(function(j){
      if(settled||!j||j.app!=='zuhui-workbench') return;
      port=pp; window.__bridgePort=pp;
      var api={};
      BRIDGE_METHODS.forEach(function(m){
        api[m]=function(){ return call(m, Array.prototype.slice.call(arguments)); };
      });
      window.pywebview={api:api};
      clearTimeout(timer); settle();
    }).catch(function(){
      if(--left<=0){ clearTimeout(timer); settle(); }     // 全都连不上，不用白等
    });
  });
}
bridgeProbe(function(){
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot);
  else boot();
});
})();
