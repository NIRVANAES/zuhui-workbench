/* 背景：域扭曲 FBM 光场 + 四层 IU 元素。
   玻璃要有「背后有东西」才成立 —— 没有这层，backdrop-filter 就只是在模糊纯色。

   IU 元素（2026-10-02 用户从 4 个候选里全选，并要求「明显一点」）：
     A 丁香花瓣飘落 —— 《LILAC》专辑意象
     B 应援棒光海   —— 下半部疏落光点随波起伏，官方应援色霓虹黄
     C 丁香枝剪影   —— 两侧圆锥花序，与桌面图版同构
     D 夜信·星月    —— 月牙 + 稀疏星点
   调色板：淡紫（《LILAC》）+ 霓虹黄（官方应援色 네온 옐로우）。
   ⚠️ 元素一律「往深紫方向 mix」，不用叠加发光 —— 底色接近白，低透明度叠加会被冲掉。

   ⚠️ 关键安全设计：画布默认 display:none（见 CSS），只有「确认真的画出东西了」
   才切到 display:block。原因：WebGL 画布在 alpha:false 时未绘制区域是**不透明黑**，
   一旦某台机器的 GPU 路径出问题（驱动、上下文丢失、软件渲染缺失），整页就会变成黑板，
   而 CSS 渐变完全被盖住。所以这里做三重保险：
     1. 全程 try/catch，任何异常都直接退回 CSS 渐变
     2. 首帧后 readPixels 读回多个点，确认不是全透明/全黑，才显示画布
     3. 监听 webglcontextlost，一旦丢失立即隐藏

   性能：半分辨率渲染（SCALE=0.5）· 30fps 上限 · 标签页隐藏时暂停 ·
   尊重 prefers-reduced-motion（只画一帧）。 */
(function () {
  var cv = document.getElementById('bg');
  if (!cv) return;

  function bail(msg) {
    try { cv.style.display = 'none'; } catch (e) {}
    if (msg && window.console) console.warn('bg:', msg);
  }

  try {
    var gl = cv.getContext('webgl2', { antialias: false, alpha: true, depth: false, stencil: false });
    if (!gl || gl.isContextLost()) { bail('no webgl2'); return; }

    var VS = '#version 300 es\n' +
      'in vec2 a_pos;\n' +
      'void main(){ gl_Position = vec4(a_pos, 0.0, 1.0); }';

    var FS = '#version 300 es\n' +
      'precision highp float;\n' +
      'out vec4 fragColor;\n' +
      'uniform vec2 u_res;\n' +
      'uniform float u_time;\n' +
      'const mat2 mtx = mat2(0.80, 0.60, -0.60, 0.80);\n' +
      'const vec3 C0 = vec3(0.984, 0.976, 0.996);\n' +
      'const vec3 C1 = vec3(0.906, 0.871, 0.973);\n' +
      'const vec3 C2 = vec3(0.792, 0.729, 0.925);\n' +
      'const vec3 C3 = vec3(0.925, 0.976, 0.463);\n' +
      'const vec3 LILAC = vec3(0.478, 0.365, 0.780);\n' +
      'const vec3 NEON  = vec3(0.706, 0.827, 0.098);\n' +
      'float hash12(vec2 p){\n' +
      '  vec3 p3 = fract(vec3(p.xyx) * 0.1031);\n' +
      '  p3 += dot(p3, p3.yzx + 33.33);\n' +
      '  return fract((p3.x + p3.y) * p3.z);\n' +
      '}\n' +
      'float noise(vec2 p){\n' +
      '  vec2 i = floor(p); vec2 f = fract(p);\n' +
      '  f = f * f * (3.0 - 2.0 * f);\n' +
      '  float a = hash12(i);\n' +
      '  float b = hash12(i + vec2(1.0, 0.0));\n' +
      '  float c = hash12(i + vec2(0.0, 1.0));\n' +
      '  float d = hash12(i + vec2(1.0, 1.0));\n' +
      '  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);\n' +
      '}\n' +
      'float fbm(vec2 p){\n' +
      '  float f = 0.0; float a = 0.5;\n' +
      '  for (int i = 0; i < 4; i++) { f += a * noise(p); p = mtx * p * 2.03; a *= 0.5; }\n' +
      '  return f / 0.9375;\n' +
      '}\n' +
      /* ---- A 丁香花瓣：极坐标轮廓 + 底部凹口 ---- */
      'float petalSDF(vec2 p, float s){\n' +
      '  vec2 q = p / vec2(s * 0.52, s);\n' +
      '  float r = length(q);\n' +
      '  float a = atan(q.y, q.x);\n' +
      '  float shape = r - (0.60 + 0.40 * cos(a));\n' +
      '  float notch = length(q - vec2(0.0, -0.62)) - 0.30;\n' +
      '  return max(shape, -notch);\n' +
      '}\n' +
      'vec3 petals(vec2 uv, float t, out float cov){\n' +
      '  cov = 0.0; vec3 tint = vec3(0.0);\n' +
      '  for (int i = 0; i < 14; i++){\n' +
      '    float fi = float(i);\n' +
      '    float sd = hash12(vec2(fi * 3.7, 1.3));\n' +
      '    float sp = 0.050 + sd * 0.045;\n' +
      '    float x  = hash12(vec2(fi * 7.1, 4.4)) * 4.4 - 2.2;\n' +
      '    x += sin(t * 0.30 + fi * 1.7) * 0.24;\n' +
      '    float y  = fract(hash12(vec2(fi * 2.3, 9.1)) - t * sp) * 3.6 - 1.8;\n' +
      '    float sz = 0.075 + sd * 0.070;\n' +
      '    float rot = t * (0.20 + sd * 0.24) + fi * 1.1;\n' +
      '    vec2 p = uv - vec2(x, y);\n' +
      '    float cs = cos(rot), sn = sin(rot);\n' +
      '    p = mat2(cs, -sn, sn, cs) * p;\n' +
      '    float m = smoothstep(0.014, -0.012, petalSDF(p, sz));\n' +
      '    vec3 pc = (hash12(vec2(fi * 5.9, 2.2)) > 0.76) ? NEON : LILAC;\n' +
      '    cov += m; tint += pc * m;\n' +
      '  }\n' +
      '  tint = cov > 0.001 ? tint / cov : vec3(0.0);\n' +
      '  return tint;\n' +
      '}\n' +
      /* ---- B 应援棒光海：下半部、带抖动、不规则 ---- */
      'vec3 lightSea(vec2 uv, float t, out float cov){\n' +
      '  cov = 0.0; vec3 tint = vec3(0.0);\n' +
      '  float band = smoothstep(0.85, -0.85, uv.y);\n' +
      '  if (band < 0.004) return vec3(0.0);\n' +
      '  vec2 g = vec2(uv.x * 8.5, uv.y * 5.2 + 3.2);\n' +
      '  vec2 id = floor(g);\n' +
      '  vec2 f  = fract(g) - 0.5;\n' +
      '  float rnd = hash12(id + 11.3);\n' +
      '  float keep = step(0.48, rnd);\n' +
      '  vec2 jit = (vec2(hash12(id + 3.1), hash12(id + 8.8)) - 0.5) * 0.62;\n' +
      '  f -= jit;\n' +
      '  float wave = sin(t * 0.70 + id.x * 0.72 + id.y * 0.34) * 0.5 + 0.5;\n' +
      '  f.y -= wave * 0.18;\n' +
      '  float dotm = smoothstep(0.27, 0.015, length(f * vec2(1.0, 1.30)));\n' +
      '  float b = dotm * keep * band;\n' +
      '  vec3 lc = (rnd > 0.60) ? NEON : LILAC;\n' +
      '  cov += b * (0.45 + 0.55 * wave);\n' +
      '  tint += lc * b;\n' +
      '  tint = cov > 0.001 ? tint / cov : vec3(0.0);\n' +
      '  return tint;\n' +
      '}\n' +
      /* ---- C 丁香枝剪影：圆锥花序（四瓣花冠 + 花心） ---- */
      'float sprig(vec2 p, vec2 base, float dir, float len, float fr){\n' +
      '  float d = 1e9;\n' +
      '  for (int i = 0; i < 11; i++){\n' +
      '    float k = float(i) / 10.0;\n' +
      '    vec2 c = base + vec2(sin(k * 2.4 + dir) * 0.15, k * len);\n' +
      '    float r = fr * (1.0 - k * 0.66);\n' +
      '    for (int j = 0; j < 4; j++){\n' +
      '      float a = 1.5707963 * float(j) + k * 1.40;\n' +
      '      vec2 o = c + (r * 0.72) * vec2(cos(a), sin(a));\n' +
      '      d = min(d, length(p - o) - r * 0.30);\n' +
      '    }\n' +
      '    d = min(d, length(p - c) - r * 0.13);\n' +
      '  }\n' +
      '  return d;\n' +
      '}\n' +
      'vec3 sprigs(vec2 uv, float t, out float cov){\n' +
      '  float sway = sin(t * 0.25) * 0.045;\n' +
      '  float d1 = sprig(uv, vec2(-2.00 + sway, -1.95), 0.30, 2.75, 0.105);\n' +
      '  float d2 = sprig(uv, vec2( 2.00 - sway, -1.75), -0.36, 2.45, 0.094);\n' +
      '  cov = smoothstep(0.008, -0.016, min(d1, d2)) * 0.52;\n' +
      '  return LILAC;\n' +
      '}\n' +
      /* ---- D 夜信·星月：月牙 + 星点 ---- */
      'vec3 moonStars(vec2 uv, float t, out float cov){\n' +
      '  cov = 0.0; vec3 tint = vec3(0.0);\n' +
      '  vec2 mc = vec2(1.02, 0.74);\n' +
      '  float R = 0.30;\n' +
      '  vec2 e = vec2(0.95, 1.0);\n' +
      '  float dm  = length((uv - mc) * e) - R;\n' +
      '  float cut = length((uv - mc - vec2(-0.135, 0.02)) * e) - R * 1.04;\n' +
      '  float m = smoothstep(0.012, -0.014, max(dm, -cut));\n' +
      '  cov += m * 0.66; tint += LILAC * m;\n' +
      '  vec2 sg = uv * vec2(19.0, 12.0);\n' +
      '  vec2 sid = floor(sg); vec2 sf = fract(sg) - 0.5;\n' +
      '  float sr = hash12(sid + 7.7);\n' +
      '  float on = step(0.915, sr);\n' +
      '  float tw = 0.45 + 0.55 * sin(t * 1.7 + sr * 40.0);\n' +
      '  float st = smoothstep(0.115, 0.0, length(sf)) * on * tw;\n' +
      '  cov += st * 0.50;\n' +
      '  tint += (sr > 0.965 ? NEON : LILAC) * st;\n' +
      '  tint = cov > 0.001 ? tint / cov : vec3(0.0);\n' +
      '  return tint;\n' +
      '}\n' +
      'void main(){\n' +
      '  vec2 uv = (2.0 * gl_FragCoord.xy - u_res) / max(u_res.y, 1.0);\n' +
      '  uv *= 1.25;\n' +
      '  float t = u_time * 0.030;\n' +
      '  vec2 q = vec2(fbm(uv + vec2(0.0, t)), fbm(uv + vec2(5.2, 1.3) - vec2(t, 0.0)));\n' +
      '  vec2 r = vec2(fbm(uv + 1.35 * q + vec2(1.7, 9.2) + t * 0.7),\n' +
      '                fbm(uv + 1.35 * q + vec2(8.3, 2.8) - t * 0.6));\n' +
      '  float f = clamp(fbm(uv + 1.15 * r), 0.0, 1.0);\n' +
      '  vec3 col = mix(C0, C1, smoothstep(0.28, 0.92, f));\n' +
      '  col = mix(col, C2, smoothstep(0.58, 1.10, f) * 0.44);\n' +
      '  float d = length((uv - vec2(0.95, 0.62)) * vec2(0.85, 1.0));\n' +
      '  float neon = smoothstep(0.62, 0.98, f) * (1.0 - smoothstep(0.10, 1.05, d));\n' +
      '  col = mix(col, C3, neon * 0.24);\n' +
      /* 四层元素各自算覆盖率，最后按覆盖率加权混一次，避免互相冲淡 */
      '  float cA, cB, cC, cD;\n' +
      '  vec3 tA = petals(uv, u_time, cA);\n' +
      '  vec3 tB = lightSea(uv, u_time, cB);\n' +
      '  vec3 tC = sprigs(uv, u_time, cC);\n' +
      '  vec3 tD = moonStars(uv, u_time, cD);\n' +
      '  float cov = cA + cB + cC + cD;\n' +
      '  vec3 tint = tA * cA + tB * cB + tC * cC + tD * cD;\n' +
      '  tint = cov > 0.001 ? tint / cov : vec3(0.0);\n' +
      '  col = mix(col, tint, clamp(cov, 0.0, 1.0) * 0.62);\n' +
      '  col *= 1.0 - 0.042 * (gl_FragCoord.y / max(u_res.y, 1.0));\n' +
      '  col += (hash12(gl_FragCoord.xy * 1.7 + fract(u_time) * 37.0) - 0.5) * (1.6 / 255.0);\n' +
      '  fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);\n' +
      '}';

    function mk(type, src) {
      var s = gl.createShader(type);
      if (!s) return null;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        if (window.console) console.warn('bg shader:', gl.getShaderInfoLog(s));
        return null;
      }
      return s;
    }
    var vs = mk(gl.VERTEX_SHADER, VS), fs = mk(gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) { bail('shader compile failed'); return; }
    var pr = gl.createProgram();
    if (!pr) { bail('no program'); return; }
    gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { bail('link failed'); return; }
    gl.useProgram(pr);

    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(pr, 'a_pos');
    if (loc < 0) { bail('no attrib'); return; }
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    var uRes = gl.getUniformLocation(pr, 'u_res');
    var uTime = gl.getUniformLocation(pr, 'u_time');

    var SCALE = 0.5;
    function resize() {
      var w = Math.max(1, Math.round(innerWidth * SCALE));
      var h = Math.max(1, Math.round(innerHeight * SCALE));
      if (cv.width !== w || cv.height !== h) {
        cv.width = w; cv.height = h; gl.viewport(0, 0, w, h);
      }
      if (uRes) gl.uniform2f(uRes, w, h);
    }
    var t0 = performance.now();
    function clock() { return (performance.now() - t0) / 1000; }
    function paint(t) {
      if (uTime) gl.uniform1f(uTime, t);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    /* 首帧自检：读回若干点，全透明或全黑都判定为「没画出来」 */
    function drewSomething() {
      try {
        var px = new Uint8Array(4), best = 0;
        var pts = [[cv.width >> 1, cv.height >> 1], [4, 4],
                   [cv.width - 5, 4], [4, cv.height - 5], [cv.width - 5, cv.height - 5]];
        for (var i = 0; i < pts.length; i++) {
          gl.readPixels(pts[i][0], pts[i][1], 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
          if (px[3] < 8) continue;
          var s = px[0] + px[1] + px[2];
          if (s > best) best = s;
        }
        return best > 24;
      } catch (e) { return false; }
    }

    resize();
    paint(0);

    if (!drewSomething()) { bail('first frame is blank'); return; }

    cv.style.display = 'block';                       /* 确认无误后才露面 */

    cv.addEventListener('webglcontextlost', function (e) {
      e.preventDefault();
      bail('context lost');
    });

    /* resize 会连发几十次，用 rAF 收口：拖窗口时只重画一次，而不是每个事件一次 */
    var rzRaf = 0;
    addEventListener('resize', function () {
      if (rzRaf) return;
      rzRaf = requestAnimationFrame(function () { rzRaf = 0; resize(); paint(clock()); });
    });

    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
      var last = 0;
      (function loop(now) {
        requestAnimationFrame(loop);
        if (document.hidden) return;
        if (now - last < 33) return;                  /* 30fps 上限 */
        last = now;
        paint(clock());
      })(0);
    }
  } catch (e) {
    bail(String(e && e.message || e));
  }
})();
