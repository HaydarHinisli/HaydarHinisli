// 4ELEMENTS – lebendiger Hintergrund des Kopfbereichs (generativ, ohne Ende und ohne Ziel).
// Module schweben auf einer endlosen Fläche, durch die die Ansicht langsam treibt. Laufend finden sich
// zufällig gewählte Module (2–5) zu einem Workflow zusammen – gerade, schräg, im Bogen oder verzweigt –,
// die Kugeln dazwischen übernehmen die Farbe des nächsten Moduls, der Workflow läuft einmal durch,
// löst sich wieder und die Module ziehen weiter. Verlassen Module das Bild, entstehen vorne neue.
// Leicht gebaut: 2D-Zeichenfläche mit vorab gezeichneten Modulbildern, pausiert außerhalb des Bildes,
// bei „Bewegung reduzieren“ ein ruhiges Standbild. Daten (Module, Symbole) kommen aus #flow-data.
(function () {
  'use strict';
  var host = document.querySelector('[data-flow]');
  var dataEl = document.getElementById('flow-data');
  if (!host || !dataEl || !window.requestAnimationFrame) return;
  var data;
  try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }
  var POOL = data.modules || [];
  if (POOL.length < 6) return;
  var ICONS = data.icons || {}, GLYPHS = data.glyphs || {};
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Zufall: fest vorgebbar (?flowseed=…) für Vorschaubilder, sonst jedes Mal anders
  var seed = (function () { var m = /[?&]flowseed=(\d+)/.exec(location.search); return m ? +m[1] : (Date.now() % 2147483647); })();
  function rnd() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }
  function pick(a) { return a[Math.floor(rnd() * a.length)]; }
  var clock = typeof window.__flowClock === 'function' ? window.__flowClock : function () { return performance.now() / 1000; };

  var canvas = document.createElement('canvas');
  canvas.className = 'flow-bg__canvas';
  canvas.setAttribute('aria-hidden', 'true');
  host.appendChild(canvas);
  var g = canvas.getContext('2d');
  var DPR = Math.min(window.devicePixelRatio || 1, 2);
  var W = 0, H = 0, S = 1, blocks = [];   // S = Modulgröße in Bildpunkten (Durchmesser der Scheibe)
  function resize() {
    var r = host.getBoundingClientRect();
    W = r.width; H = r.height;
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    S = Math.max(34, Math.min(52, W / 28));
    // Hindernisse: Überschrift/Text und App-Fenster – dort entstehen keine Workflows
    blocks = Array.prototype.slice.call(host.parentElement.querySelectorAll('.hero__text, .window, .marquee')).map(function (el) {
      var b = el.getBoundingClientRect(); return { l: b.left - r.left, t: b.top - r.top, r: b.right - r.left, b: b.bottom - r.top };
    });
  }

  // ---------- Farben ----------
  function hex(c) { var n = parseInt(c.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
  function mix(a, b, t) { return [0, 1, 2].map(function (i) { return Math.round(a[i] + (b[i] - a[i]) * t); }); }
  function css(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + (a == null ? 1 : a) + ')'; }
  var WHITE = [255, 255, 255], BLACK = [0, 0, 0];

  // ---------- Modulbilder (einmal zeichnen, dann nur noch kopieren) ----------
  var sprites = {};
  function glyph(c, m, cx, cy, r, col) {
    var layers = GLYPHS[m.icon];
    c.save(); c.translate(cx - r, cy - r); c.scale(r / 32, r / 32); c.lineCap = 'round'; c.lineJoin = 'round';
    if (layers) {
      var map = { fg: '#fff', bg: css(col), light: css(mix(col, WHITE, 0.55)) };
      layers.forEach(function (l) {
        var p = new Path2D(l.d);
        if (l.fill) { c.fillStyle = map[l.fill]; c.fill(p); } else { c.strokeStyle = map[l.stroke]; c.lineWidth = l.w; c.stroke(p); }
      });
    } else if (ICONS[m.icon]) {   // Liniensymbol im 24er-Raster, mittig auf 64
      c.translate(14, 14); c.scale(1.5, 1.5); c.strokeStyle = '#fff'; c.lineWidth = 1.7; c.fillStyle = 'none';
      var svg = ICONS[m.icon], mm;
      var re = / d="([^"]+)"/g; while ((mm = re.exec(svg))) c.stroke(new Path2D(mm[1]));
      var rr = /<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="([\d.]+)"/g;
      while ((mm = rr.exec(svg))) { c.beginPath(); roundRect(c, +mm[1], +mm[2], +mm[3], +mm[4], +mm[5]); c.stroke(); }
      var rc = /<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"/g;
      while ((mm = rc.exec(svg))) { c.beginPath(); c.arc(+mm[1], +mm[2], +mm[3], 0, 7); c.stroke(); }
    }
    c.restore();
  }
  function roundRect(c, x, y, w, h, r) {
    c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  }
  function sprite(m) {
    var key = m.app + '|' + S;
    if (sprites[key]) return sprites[key];
    var col = hex(m.color), R = S / 2, pad = R * 0.9, w = S + pad * 2, h = S + pad * 2 + R * 0.9;
    var c = document.createElement('canvas');
    c.width = Math.round(w * DPR); c.height = Math.round(h * DPR);
    var x = c.getContext('2d'); x.scale(DPR, DPR);
    var cx = w / 2, cy = pad + R;
    // Schatten am Boden
    x.save(); x.translate(cx + R * 0.15, cy + R * 1.08); x.scale(1, 0.22);
    var sh = x.createRadialGradient(0, 0, 0, 0, 0, R * 1.05); sh.addColorStop(0, 'rgba(20,30,40,0.22)'); sh.addColorStop(1, 'rgba(20,30,40,0)');
    x.fillStyle = sh; x.beginPath(); x.arc(0, 0, R * 1.05, 0, 7); x.fill(); x.restore();
    // Halbmond-Anschlüsse
    var conn = mix(col, [28, 31, 35], 0.3);
    x.fillStyle = css(conn);
    x.beginPath(); x.arc(cx - R * 1.12, cy, R * 0.32, Math.PI / 2, -Math.PI / 2, true); x.closePath(); x.fill();
    x.beginPath(); x.arc(cx + R * 1.12, cy, R * 0.32, -Math.PI / 2, Math.PI / 2); x.closePath(); x.fill();
    // Gewölbte Scheibe: Licht oben links, Eigenschatten unten rechts, Glanzpunkt
    x.save(); x.beginPath(); x.arc(cx, cy, R, 0, 7); x.clip();
    var body = x.createRadialGradient(cx - R * 0.32, cy - R * 0.38, R * 0.08, cx - R * 0.08, cy - R * 0.1, R * 1.12);
    body.addColorStop(0, css(mix(col, WHITE, 0.42))); body.addColorStop(0.45, css(col)); body.addColorStop(0.9, css(mix(col, BLACK, 0.34))); body.addColorStop(1, css(mix(col, BLACK, 0.34)));
    x.fillStyle = body; x.fillRect(cx - R, cy - R, S, S);
    var sp = x.createRadialGradient(cx - R * 0.34, cy - R * 0.42, 0, cx - R * 0.34, cy - R * 0.42, R * 0.34);
    sp.addColorStop(0, 'rgba(255,255,255,0.6)'); sp.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = sp; x.fillRect(cx - R, cy - R, S, S);
    x.restore();
    x.save(); x.shadowColor = 'rgba(0,0,0,0.2)'; x.shadowBlur = 4; x.shadowOffsetX = 1; x.shadowOffsetY = 2;
    glyph(x, m, cx, cy, R, col); x.restore();
    // Name
    x.font = '500 ' + Math.round(S * 0.2) + 'px Geist, system-ui, sans-serif';
    x.textAlign = 'center'; x.textBaseline = 'top'; x.fillStyle = '#3b3934';
    x.fillText(m.app, cx, cy + R + R * 0.34);
    sprites[key] = { img: c, w: w, h: h, ox: cx, oy: cy };
    return sprites[key];
  }
  function glow(col) {   // weicher Schein hinter einem aktiven Modul
    var k = 'glow' + col.join();
    if (sprites[k]) return sprites[k];
    var c = document.createElement('canvas'); c.width = c.height = 128;
    var x = c.getContext('2d'), gr = x.createRadialGradient(64, 64, 10, 64, 64, 64);
    gr.addColorStop(0, css(col, 0.55)); gr.addColorStop(1, css(col, 0));
    x.fillStyle = gr; x.fillRect(0, 0, 128, 128);
    return (sprites[k] = c);
  }

  // ---------- Welt ----------
  var cam = { x: 0, y: 0 };
  var mods = [], links = [], groups = [];
  var recent = [];                 // zuletzt gezeigte Module – nicht sofort wieder verwenden
  function nextModule() {
    var tries = 0, m;
    do { m = pick(POOL); tries++; } while (tries < 20 && (recent.indexOf(m) > -1 || mods.some(function (o) { return o.m === m; })));
    recent.push(m); if (recent.length > Math.min(18, POOL.length - 8)) recent.shift();
    return m;
  }
  function spawn(x, y) {
    var z = 0.55 + rnd() * 0.45;   // Tiefe: 1 = vorne, kleiner = weiter hinten (kleiner, blasser, langsamer)
    mods.push({ m: nextModule(), x: x, y: y, z: z, vx: (rnd() - 0.5) * 14, vy: (rnd() - 0.5) * 10, tx: null, ty: null, busy: null, lit: 0, born: clock() });
  }
  function screen(o) {             // Welt → Bildschirm (Tiefe bewegt sich langsamer: Parallaxe)
    return { x: (o.x - cam.x) * o.z + W / 2, y: (o.y - cam.y) * o.z + H / 2 };
  }
  function fill(initial) {
    var target = Math.round((W * H) / (S * S * 7));
    target = Math.max(W < 700 ? 7 : 10, Math.min(W < 700 ? 10 : 34, target));
    var guard = 0;
    while (mods.length < target && guard++ < 200) {
      var z = 1, x, y, ok;
      if (initial) { x = cam.x + (rnd() - 0.5) * W * 1.3; y = cam.y + (rnd() - 0.5) * H * 1.2; }
      else {        // am Rand, in Fahrtrichtung, außerhalb des Bildes
        var ang = Math.atan2(drift.y, drift.x) + (rnd() - 0.5) * 1.6;
        var d = Math.hypot(W, H) * 0.62;
        x = cam.x + Math.cos(ang) * d; y = cam.y + Math.sin(ang) * d;
      }
      ok = mods.every(function (o) { return Math.hypot(o.x - x, o.y - y) > S * 2.2 * z; });
      if (ok) spawn(x, y);
    }
  }

  // Fahrt durch die endlose Fläche: Richtung ändert sich langsam und ziellos
  var drift = { x: 1, y: 0.2 }, driftA = rnd() * 6.28;
  function steerCamera(dt, t) {
    driftA += (Math.sin(t * 0.07) * 0.5 + Math.sin(t * 0.031 + 1.7) * 0.5) * dt * 0.35;
    drift.x = Math.cos(driftA); drift.y = Math.sin(driftA) * 0.6;
    cam.x += drift.x * dt * 16; cam.y += drift.y * dt * 16;
  }

  function freeAt(x, y, pad) {   // Punkt liegt im Bild und nicht hinter Text oder Fenster
    if (x < pad || x > W - pad || y < pad || y > H - pad) return false;
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i];
      if (x > b.l - pad && x < b.r + pad && y > b.t - pad && y < b.b + pad) return false;
    }
    return true;
  }

  function clear(x, y) {           // Abstand zu Modulen anderer laufender Workflows
    for (var i = 0; i < groups.length; i++) {
      var gm = groups[i].mods;
      for (var j = 0; j < gm.length; j++) {
        var o = gm[j], px = (o.tx - cam.x) * o.zt + W / 2, py = (o.ty - cam.y) * o.zt + H / 2;
        if (Math.hypot(px - x, py - y) < S * 2.4) return false;
      }
    }
    return true;
  }

  // ---------- Workflows: finden, laufen, lösen ----------
  var SHAPES = ['line', 'diag', 'arc', 'zig', 'branch'];
  function layout(n, shape, ang) {
    var gap = S * (2.35 + rnd() * 0.5), pts = [], i;
    if (shape === 'branch' && n >= 4) {           // 1 → Router → zwei Zweige
      pts = [[0, 0], [gap, 0], [gap * 2, -gap * 0.62], [gap * 2, gap * 0.62]];
      if (n === 5) pts.push([gap * 3, -gap * 0.62]);
    } else {
      for (i = 0; i < n; i++) {
        var y = 0;
        if (shape === 'arc') y = -Math.sin((i / (n - 1)) * Math.PI) * gap * 0.55;
        if (shape === 'zig') y = (i % 2 ? 1 : -1) * gap * 0.28;
        pts.push([i * gap, y]);
      }
    }
    var a = ang, c = Math.cos(a), s = Math.sin(a);
    var mx = 0, my = 0; pts.forEach(function (p) { mx += p[0]; my += p[1]; }); mx /= pts.length; my /= pts.length;
    return pts.map(function (p) { var x = p[0] - mx, y = p[1] - my; return [x * c - y * s, x * s + y * c]; });
  }
  function startGroup(t) {
    // Ankerpunkt im freien Bereich suchen; die nächstgelegenen Module (auch hinter dem Text) fliegen dorthin
    var anchor = null;
    for (var k = 0; k < 30 && !anchor; k++) {
      var ax = rnd() * W, ay = rnd() * Math.min(H, window.innerHeight * 1.1);
      if (freeAt(ax, ay, S * 1.2) && clear(ax, ay)) anchor = { x: ax, y: ay };
    }
    if (!anchor) return;
    var free = mods.filter(function (o) {
      if (o.busy) return false;
      var p = screen(o); return p.x > -S && p.x < W + S && p.y > -S && p.y < H + S;
    });
    if (free.length < 2) return;
    var n = Math.min(free.length, 2 + Math.floor(rnd() * (W < 700 ? 2 : 4)));   // 2–5 Module (schmal: 2–3)
    var shape = n >= 4 && rnd() < 0.35 ? 'branch' : pick(SHAPES.slice(0, 4));
    var near = free.slice().sort(function (a, b) {
      var pa = screen(a), pb = screen(b);
      return Math.hypot(pa.x - anchor.x, pa.y - anchor.y) - Math.hypot(pb.x - anchor.x, pb.y - anchor.y);
    }).slice(0, n);
    // Reihenfolge entlang der Hauptrichtung, damit sich Wege nicht kreuzen
    // Form und Richtung so wählen, dass der ganze Workflow im freien Bereich liegt (mehrere Versuche)
    var z = near.reduce(function (s, o) { return s + o.z; }, 0) / n;
    var sp0 = anchor, pts = null, ang, sx, sy;
    for (var tries = 0; tries < 10 && !pts; tries++) {
      var side = sp0.x < W * 0.3 || sp0.x > W * 0.7;
      ang = side || rnd() < 0.3 ? (rnd() < 0.5 ? 1 : -1) * Math.PI / 2 + (rnd() - 0.5) * 0.8 : (rnd() - 0.5) * 0.8;
      if (shape === 'diag') ang += (rnd() < 0.5 ? 1 : -1) * 0.45;
      var cand = layout(n, shape, ang);
      sx = sp0.x + (rnd() - 0.5) * S; sy = sp0.y + (rnd() - 0.5) * S;
      if (cand.every(function (p) { return freeAt(sx + p[0], sy + p[1] + S * 0.25, S * 0.75) && clear(sx + p[0], sy + p[1]); })) pts = cand;
      else if (tries > 4 && n > 2) { n--; near = near.slice(0, n); if (shape === 'branch' && n < 4) shape = 'line'; }
    }
    if (!pts) return;
    var cx = cam.x + (sx - W / 2) / z, cy = cam.y + (sy - H / 2) / z;
    // Reihenfolge entlang der Hauptrichtung, damit sich die Wege beim Zusammenfinden nicht kreuzen
    near.sort(function (a, b) { return (a.x * Math.cos(ang) + a.y * Math.sin(ang)) - (b.x * Math.cos(ang) + b.y * Math.sin(ang)); });
    var grp = { mods: near, t0: t, shape: shape, links: [] };
    near.forEach(function (o, i) { o.busy = grp; o.z0 = o.z; o.zt = z; o.fx = o.x; o.fy = o.y; o.tx = cx + pts[i][0] / z; o.ty = cy + pts[i][1] / z; o.lit = 0; });
    var pairs = [];
    if (shape === 'branch') { pairs = [[0, 1], [1, 2], [1, 3]]; if (n === 5) pairs.push([2, 4]); }
    else for (var i = 0; i < n - 1; i++) pairs.push([i, i + 1]);
    grp.links = pairs.map(function (p, k) { return { a: near[p[0]], b: near[p[1]], order: k }; });
    groups.push(grp);
  }
  // Zeiten (Sekunden seit Start der Gruppe)
  var T_GATHER = 2.2, T_LINK = 0.7, T_STEP = 0.55, T_HOLD = 1.4, T_RELEASE = 1.2;
  function ease(v) { v = v < 0 ? 0 : v > 1 ? 1 : v; return v < 0.5 ? 4 * v * v * v : 1 - Math.pow(-2 * v + 2, 3) / 2; }
  function clamp(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function updateGroup(grp, t) {
    var age = t - grp.t0, n = grp.mods.length;
    var runEnd = T_GATHER + T_LINK + n * T_STEP, end = runEnd + T_HOLD;
    var gp = ease(age / T_GATHER);
    grp.mods.forEach(function (o, i) {
      if (age < T_GATHER) {
        o.x = o.fx + (o.tx - o.fx) * gp; o.y = o.fy + (o.ty - o.fy) * gp; o.z = o.z0 + (o.zt - o.z0) * gp;
      }
      var on = T_GATHER + T_LINK + i * T_STEP;            // Modul i arbeitet
      o.lit = age < on ? 0 : age < end ? 1 : 1 - clamp((age - end) / T_RELEASE);
    });
    grp.linkP = clamp((age - T_GATHER + 0.2) / T_LINK);   // Kugeln entstehen
    grp.flow = clamp((age - T_GATHER - T_LINK) / (n * T_STEP));
    grp.fade = age < end ? 1 : 1 - clamp((age - end) / T_RELEASE);
    if (age > end + T_RELEASE) {
      grp.mods.forEach(function (o) { o.busy = null; o.lit = 0; var a = rnd() * 6.28; o.vx = Math.cos(a) * 16; o.vy = Math.sin(a) * 12; });
      return false;
    }
    return true;
  }

  // ---------- Bildschleife ----------
  var last = clock(), nextGroup = clock() + 0.6, running = false, visible = true;
  function frame() {
    if (!running) return;
    var t = clock(), dt = Math.min(0.05, t - last); last = t;
    steerCamera(dt, t);
    mods.forEach(function (o) {
      if (o.busy) return;
      o.x += o.vx * dt; o.y += o.vy * dt;
      o.vx += (rnd() - 0.5) * 2 * dt; o.vy += (rnd() - 0.5) * 2 * dt;   // leichtes Taumeln
    });
    groups = groups.filter(function (grp) { return updateGroup(grp, t); });
    if (t > nextGroup && groups.length < 3) { startGroup(t); nextGroup = t + 1.1 + rnd() * 1.6; }
    // Module weit außerhalb des Bildes entfernen, vorne neue entstehen lassen
    var far = Math.hypot(W, H) * 0.85;
    mods = mods.filter(function (o) { return o.busy || Math.hypot((o.x - cam.x) * o.z, (o.y - cam.y) * o.z) < far; });
    fill(false);
    draw(t);
    requestAnimationFrame(frame);
  }
  function drawLink(L, grp) {
    var pa = screen(L.a), pb = screen(L.b), R = (S / 2) * ((L.a.z + L.b.z) / 2);
    var dx = pb.x - pa.x, dy = pb.y - pa.y, len = Math.hypot(dx, dy);
    if (len < R * 2.6) return;
    var ux = dx / len, uy = dy / len, start = R * 1.45, stop = len - R * 1.45, span = stop - start;
    var count = Math.max(3, Math.round(span / (R * 0.42)));
    var ca = hex(L.a.m.color), cb = hex(L.b.m.color);
    var shown = Math.round(count * grp.linkP);
    var total = grp.links.length, reach = grp.flow * total - L.order;   // wie weit der Durchlauf diese Verbindung erreicht hat
    for (var i = 0; i < shown; i++) {
      var f = count === 1 ? 0.5 : i / (count - 1);
      var x = pa.x + ux * (start + span * f), y = pa.y + uy * (start + span * f);
      var col = mix(ca, cb, f), on = reach > f;
      var r = R * (on ? 0.2 : 0.16);
      var a = grp.fade * (on ? 0.85 : 0.45);
      var gr = g.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.1, x, y, r);
      gr.addColorStop(0, css(mix(col, WHITE, 0.45), a)); gr.addColorStop(0.6, css(col, a)); gr.addColorStop(1, css(mix(col, BLACK, 0.3), a));
      g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    }
  }
  function draw(t) {
    g.setTransform(DPR, 0, 0, DPR, 0, 0);
    g.clearRect(0, 0, W, H);
    groups.forEach(function (grp) { grp.links.forEach(function (L) { drawLink(L, grp); }); });
    mods.slice().sort(function (a, b) { return a.z - b.z; }).forEach(function (o) {
      var p = screen(o), sp = sprite(o.m), k = o.z;
      var w = sp.w * k, h = sp.h * k;
      if (p.x < -w || p.x > W + w || p.y < -h || p.y > H + h) return;
      var age = t - o.born, fadeIn = clamp(age / 1.2);
      var alpha = (0.3 + 0.35 * (o.z - 0.55) / 0.45 + o.lit * 0.3) * fadeIn * (W < 700 ? 0.75 : 1);   // Hintergrund: zurückhaltend, aktive Module etwas kräftiger
      if (o.lit > 0.01) {
        var gl = glow(hex(o.m.color)), gs = S * 2.4 * k;
        g.globalAlpha = o.lit * 0.55 * fadeIn; g.drawImage(gl, p.x - gs / 2, p.y - gs / 2, gs, gs);
      }
      g.globalAlpha = Math.min(1, alpha);
      g.drawImage(sp.img, p.x - sp.ox * k, p.y - sp.oy * k, w, h);
      if (o.lit > 0.6) {   // „1“ nach getaner Arbeit
        var bx = p.x + S * 0.4 * k, by = p.y - S * 0.4 * k, br = S * 0.16 * k;
        g.globalAlpha = (o.lit - 0.6) / 0.4 * Math.min(1, alpha + 0.2);
        g.fillStyle = '#3ddc97'; g.beginPath(); g.arc(bx, by, br, 0, 7); g.fill();
        g.lineWidth = br * 0.28; g.strokeStyle = '#fff'; g.stroke();
        g.fillStyle = '#0b1f16'; g.font = '600 ' + Math.round(br * 1.2) + 'px Geist, system-ui, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillText('1', bx, by + br * 0.05);
      }
    });
    g.globalAlpha = 1;
  }

  function start() { if (running || !visible) return; running = true; last = clock(); requestAnimationFrame(frame); }
  function stop() { running = false; }
  function init() {
    resize(); fill(true);
    if (reduce) {           // ruhiges Standbild: ein fertiger Workflow in der Mitte
      startGroup(0); groups.forEach(function (grp) { updateGroup(grp, 0 + T_GATHER + T_LINK + grp.mods.length * T_STEP + 0.1); });
      draw(99); return;
    }
    start();
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (en) { visible = en[0].isIntersecting; if (visible && !document.hidden) start(); else stop(); }).observe(host);
    }
    document.addEventListener('visibilitychange', function () { if (document.hidden) stop(); else if (visible) start(); });
    var rt; window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { sprites = {}; resize(); }, 200); });
  }
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(init);
})();
