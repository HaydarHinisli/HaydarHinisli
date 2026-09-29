// 4ELEMENTS – 3D-Intro (Quelle). Wird mit `npm run build:intro3d` zu assets/js/intro3d.js gebündelt.
// Ego-Fahrt geradeaus entlang der Workflow-Kette (Shopify → Google Sheets → OpenAI → Gmail), ohne Anhalten.
// Die Kette besteht aus Kugeln, deren Farbe zum nächsten Modul übergeht. Jedes Modul leuchtet auf, sobald man
// sich ihm nähert, der Ring läuft im Uhrzeigersinn, dann erscheint die „1“; danach fährt man hindurch.
// Nach dem letzten Modul schwenkt die Kamera zur Seite, bis die ganze Kette zu sehen ist, und die vier Module
// gleiten exakt an ihren Platz im Kopfbereich der Seite. Erst dann erscheint die Seite. Gesamtdauer knapp 5 Sekunden.
import {
  WebGLRenderer, Scene, Fog, PerspectiveCamera, Sprite, SpriteMaterial, CanvasTexture, MeshBasicMaterial,
  PlaneGeometry, Mesh, Color, RepeatWrapping, SRGBColorSpace, LinearMipmapLinearFilter,
  Vector3, Vector2, Raycaster, Plane,
} from 'three';

const ACCENT = '#3ddc97';
// Dunkles Thema der Website („futur“): Intro fährt ebenfalls im Dunkeln
const DARK = typeof document !== 'undefined' && document.documentElement.classList.contains('theme-futur');
const BG = DARK ? 0x05070a : 0xffffff;
const P = DARK
  ? { plate: 'rgba(14,19,26,0.92)', name: '#eef2f5', nameIdle: '#5d6773', badge: '#1c232b', badgeIdle: '#141a20', nr: '#a9b3bd', nrIdle: '#4f5a66', dot: '#1b2a24', floor: '#05070a', idleMix: '#1a2027' }
  : { plate: '#ffffff', name: '#1c1f23', nameIdle: '#9aa1a9', badge: '#e5e7ea', badgeIdle: '#eef0f2', nr: '#525961', nrIdle: '#b4bac1', dot: '#d3d8dd', floor: '#fff', idleMix: '#e6e9ec' };
const GAP = 6.5;               // Abstand der Module (Welteinheiten, Fahrtrichtung x)
const EYE = 1.35;              // Augenhöhe über der Kette
const FLOOR = -0.04;           // Boden knapp unter der Kette
const MOD = 3.4;               // Größe der Modul-Tafel
const RUN = 2.6;               // Strecke, auf der der Ring einmal herumläuft
const DONE_AT = 3.5;           // Abstand, bei dem das Modul fertig ist (danach „1“, dann Durchfahrt)
const DOTS = 6;                // Kugeln je Verbindung

export function run(o) {
  const { container, portrait, onDone } = o;
  const MODS = o.mods.filter((m) => m.hero).map((m, i) => ({ ...m, nr: i + 1 }));
  const GLYPHS = o.glyphs || {};
  const W = window.innerWidth, H = window.innerHeight;
  const clock = () => (typeof window.__introClock === 'function' ? window.__introClock() : (performance.now() - t0) / 1000);

  // ---------- Renderer ----------
  const renderer = new WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(W, H);
  renderer.setClearColor(BG);
  renderer.outputColorSpace = SRGBColorSpace;
  const aniso = renderer.capabilities.getMaxAnisotropy();
  const canvas = renderer.domElement;
  canvas.className = 'intro__canvas';
  container.appendChild(canvas);
  const scene = new Scene();
  scene.fog = new Fog(BG, 5, 9.5);

  // ---------- Boden: dezentes Punktraster, zeigt Tempo und Tiefe ----------
  const dc = document.createElement('canvas'); dc.width = dc.height = 64;
  const dg = dc.getContext('2d');
  dg.fillStyle = P.floor; dg.fillRect(0, 0, 64, 64); dg.fillStyle = DARK ? '#1f5a44' : P.dot;
  dg.beginPath(); dg.arc(32, 32, 3, 0, 7); dg.fill();
  const ftex = new CanvasTexture(dc); ftex.wrapS = ftex.wrapT = RepeatWrapping; ftex.repeat.set(120, 120); ftex.anisotropy = aniso; ftex.colorSpace = SRGBColorSpace;
  const floorMat = new MeshBasicMaterial({ map: ftex, transparent: true });
  const floor = new Mesh(new PlaneGeometry(200, 200), floorMat);
  floor.rotation.x = -Math.PI / 2; floor.position.set(10, FLOOR - 0.001, 0); scene.add(floor);

  // ---------- Kette: Kugeln mit Licht und Schatten ----------
  // Jede Kugel wird mit der Entfernung so verkleinert, dass sie nie in die nächste hineinragt (sonst stapeln
  // sie sich aus der Ego-Höhe). Noch nicht erreichte Kugeln sind blasser.
  const shadowTex = shadowTexture();
  const dots = [];
  for (let k = -1; k < MODS.length - 1; k++) {
    const a = new Color(k < 0 ? '#d5dade' : MODS[k].color), b = new Color(MODS[k + 1].color);
    const x0 = k < 0 ? -9 : k * GAP + 0.9, x1 = (k + 1) * GAP - 0.9, n = k < 0 ? 8 : DOTS, step = (x1 - x0) / (n - 1);
    for (let i = 0; i < n; i++) {
      const col = a.clone().lerp(b, i / (n - 1));
      const sp = new Sprite(new SpriteMaterial({ map: ballTexture(col, aniso), depthTest: false, transparent: true }));
      const sh = new Mesh(new PlaneGeometry(1, 1), new MeshBasicMaterial({ map: shadowTex, transparent: true, depthTest: false, depthWrite: false }));
      sh.rotation.x = -Math.PI / 2; sh.renderOrder = 0.5;
      scene.add(sh, sp);
      dots.push({ x: x0 + step * i, step, sp, sh });
    }
  }
  function placeDots(cx) {
    for (const d of dots) {
      const D = d.x - cx;
      const vis = D > 0.2;
      d.sp.visible = d.sh.visible = vis;
      if (!vis) continue;
      // Winkelabstand zweier Kugeln ≈ h·s/(D²+h²), Winkelgröße ≈ S/√(D²+h²)
      const size = Math.min(0.46, (0.72 * EYE * d.step) / Math.hypot(D, EYE));
      d.sp.scale.set(size, size, 1); d.sp.position.set(d.x, FLOOR + size / 2, 0); d.sp.renderOrder = 1 + 1 / D;
      d.sp.material.opacity = d.x < cx + 0.6 ? 1 : 0.62;
      d.sh.scale.set(size * 1.5, size * 1.15, 1); d.sh.position.set(d.x + size * 0.3, FLOOR, size * 0.22);
    }
  }

  // ---------- Module: Tafel „blass“ und Tafel „leuchtet/fertig“, dazu der Fortschrittsring ----------
  const texOf = (m, st) => { const t = new CanvasTexture(moduleCanvas(m, st, GLYPHS)); t.colorSpace = SRGBColorSpace; t.anisotropy = aniso; return t; };
  const units = MODS.map((m, i) => {
    const y = FLOOR + MOD / 2 - (55 / 640) * MOD;               // Unterkante der Beschriftung steht auf dem Boden
    const idle = new Sprite(new SpriteMaterial({ map: texOf(m, { state: 'idle' }), depthTest: false, transparent: true }));
    const lit = new Sprite(new SpriteMaterial({ map: texOf(m, { state: 'active' }), depthTest: false, transparent: true, opacity: 0 }));
    const done = texOf(m, { state: 'done' });
    // „bare“: fertiges Modul ohne Beschriftung und Schein – so sieht es im Kopfbereich der Seite aus
    const bare = new Sprite(new SpriteMaterial({ map: texOf(m, { state: 'done', bare: true }), depthTest: false, transparent: true, opacity: 0 }));
    for (const s of [idle, lit, bare]) { s.scale.set(MOD, MOD, 1); s.position.set(i * GAP, y, 0); scene.add(s); }
    idle.renderOrder = 10 - i; lit.renderOrder = 10.1 - i; bare.renderOrder = 10.15 - i;
    const rc = document.createElement('canvas'); rc.width = rc.height = 256;
    const rtex = new CanvasTexture(rc); rtex.colorSpace = SRGBColorSpace;
    const ring = new Sprite(new SpriteMaterial({ map: rtex, depthTest: false, transparent: true }));
    const rs = (2 * 128 * (176 / 640) * MOD) / 118;             // Ring (Radius 176 px der Tafel) auf 118 von 128 px
    ring.scale.set(rs, rs, 1); ring.position.set(i * GAP, y + (70 / 640) * MOD, 0); ring.renderOrder = 10.2 - i; ring.visible = false;
    scene.add(ring);
    return { m, i, idle, lit, bare, done, ring, rc, rtex, drawn: -1, isDone: false, y };
  });
  function drawRing(u, p) {
    if (Math.abs(u.drawn - p) < 0.01) return;
    const g = u.rc.getContext('2d'); g.clearRect(0, 0, 256, 256);
    g.lineWidth = 11; g.lineCap = 'round';
    g.beginPath(); g.arc(128, 128, 118, 0, 7); g.strokeStyle = 'rgba(61,220,151,0.25)'; g.stroke();
    g.beginPath(); g.arc(128, 128, 118, -Math.PI / 2, -Math.PI / 2 + p * Math.PI * 2); g.strokeStyle = ACCENT; g.stroke();
    u.rtex.needsUpdate = true; u.drawn = p;
  }

  // ---------- Fahrt: sanft anfahren, dann gleichmäßig – ohne Anhalten ----------
  const X0 = -5.2, V = 6.3, ACC = 0.45;                          // Start, Geschwindigkeit, Anfahrzeit
  const LAST = (MODS.length - 1) * GAP - DONE_AT;                // hier ist das letzte Modul fertig
  const T_LAST = (LAST - X0 + (V * ACC) / 2) / V;                // Zeitpunkt dafür
  function camX(s) {
    if (s < ACC) return X0 + (V * s * s) / (2 * ACC);
    return X0 + (V * ACC) / 2 + V * (s - ACC);
  }
  const FOV = portrait ? 80 : 58;
  const cam = new PerspectiveCamera(FOV, W / H, 0.05, 200);

  // ---------- Schwenk zur Seite: danach liegt die Kette waagerecht im Bild wie im Kopfbereich ----------
  const HOLD = 0.12;                                             // „1“ bei Gmail kurz stehen lassen
  const T_SWING = T_LAST + HOLD, SWING = 0.75, STAG = 0.05;
  const MID = ((MODS.length - 1) * GAP) / 2;
  const SIDE_POS = new Vector3(MID, 1.1, portrait ? 26 : 15), SIDE_LOOK = new Vector3(MID, 1.1, 0);
  const egoPos = new Vector3(), egoLook = new Vector3(), look = new Vector3();
  function cameraAt(s) {
    let x;
    if (s < T_SWING) x = camX(s);
    else {                                                        // weiter vorwärts, dabei abbremsen
      const b = clamp((s - T_SWING) / SWING);
      x = camX(T_SWING) + V * SWING * 0.3 * (b - (b * b) / 2);
    }
    egoPos.set(x, EYE, 0); egoLook.set(x + 5.2, 1.3, 0);
    const e = smooth((s - T_SWING) / SWING);
    cam.position.copy(egoPos).lerp(SIDE_POS, e);
    look.copy(egoLook).lerp(SIDE_LOOK, e);
    cam.up.set(0, 1, 0);
    cam.lookAt(look);
    scene.fog.near = 5 + e * 40; scene.fog.far = 9.5 + e * 60;   // in der Übersicht kein Nebel
    return x;
  }

  // Zielplätze: die Modulscheiben im Kopfbereich der Seite, übertragen auf die Ebene der Kette (Seitenansicht)
  const heroBodies = o.heroBodies || [];
  let targets = null;
  function computeTargets() {
    cam.position.copy(SIDE_POS); cam.up.set(0, 1, 0); cam.lookAt(SIDE_LOOK); cam.updateMatrixWorld();
    const ray = new Raycaster(), v = new Vector2(), plane = new Plane(new Vector3(0, 0, 1), 0);
    targets = units.map((u, i) => {
      const r = heroBodies[i] && heroBodies[i].getBoundingClientRect();
      if (!r || !r.width) return null;
      v.set(((r.left + r.width / 2) / W) * 2 - 1, -((r.top + r.height / 2) / H) * 2 + 1);
      ray.setFromCamera(v, cam);
      const hit = new Vector3(); if (!ray.ray.intersectPlane(plane, hit)) return null;
      const dist = -hit.clone().applyMatrix4(cam.matrixWorldInverse).z;
      const wpp = (2 * dist * Math.tan((FOV * Math.PI) / 360)) / H;   // Welteinheiten pro Bildpunkt
      const k = (r.width * wpp * 640) / 300;                           // Scheibe = 300 von 640 px der Tafel
      return { pos: hit.clone().add(new Vector3(0, -(70 / 640) * k, 0)), k };  // Scheibe liegt über der Tafelmitte
    });
  }

  // ---------- Übergang zur Seite ----------
  const LAND = T_SWING + SWING + STAG * (MODS.length - 1);
  const REVEAL = LAND - 0.35, FADE = 0.4;                        // Seite erscheint, während die Module ankommen
  const pageEls = o.pageEls || [];
  let revealed = false;

  // ---------- Bildschleife ----------
  let t0 = performance.now(), stopped = false;
  function frame() {
    if (stopped || !canvas.isConnected) return;
    const s = clock();
    if (s >= T_SWING && !targets) computeTargets();
    const cx = cameraAt(s);
    placeDots(cx);
    const swing = s >= T_SWING ? clamp((s - T_SWING) / SWING) : 0;
    for (const u of units) {
      const mx = u.i * GAP, D = mx - cx;
      const start = u.i === 0 ? X0 : mx - DONE_AT - RUN;         // ab hier arbeitet das Modul
      const len = u.i === 0 ? mx - DONE_AT - X0 : RUN;
      const p = clamp((cx - start) / len);
      const on = u.i === 0 ? smooth(s / 0.35) : smooth((cx - (start - 0.9)) / 0.9);   // aufleuchten
      u.lit.material.opacity = on;
      const done = p >= 1;
      if (done !== u.isDone) { u.isDone = done; u.lit.material.map = done ? u.done : u.lit.material.map; u.lit.material.needsUpdate = true; }
      u.ring.visible = p > 0 && !done;
      if (u.ring.visible) drawRing(u, p);
      // „1“ ploppt kurz auf
      const pop = done ? clamp((cx - start - len) / 1.2) : 0;
      const b = done && pop < 1 ? 1 + 0.06 * Math.sin(Math.PI * pop) : 1;
      u.lit.scale.set(MOD * b, MOD * b, 1);
      if (s < T_SWING) {
        // Durchfahren: kurz vor dem Modul ausblenden
        const pass = clamp((D - 1.5) / 1.1);
        u.idle.material.opacity = pass; u.lit.material.opacity *= pass; u.ring.material.opacity = pass;
        u.idle.visible = u.lit.visible = D > 0.3;
        u.bare.visible = false;
        continue;
      }
      // Schwenk: alle Module wieder sichtbar, sie gleiten an ihren Platz im Kopfbereich; die Beschriftung
      // blendet aus (die Seite hat ihre eigene), zurück bleibt das fertige Modul wie im Kopfbereich
      const e = easeInOut(clamp((s - T_SWING - u.i * STAG) / SWING));
      const T = targets && targets[u.i];
      const base = new Vector3(u.i * GAP, u.y, 0);
      const pos = T ? base.lerp(T.pos, e) : base;
      const k = T ? MOD + (T.k - MOD) * e : MOD;
      u.idle.visible = u.ring.visible = false;
      u.lit.visible = u.bare.visible = true;
      u.lit.material.opacity = 1 - e; u.bare.material.opacity = e;
      for (const sp of [u.lit, u.bare]) { sp.position.copy(pos); sp.scale.set(k, k, 1); }
    }
    if (swing > 0) {                                               // Kette und Boden treten zurück
      const f = 1 - clamp(swing * 1.8);
      for (const d of dots) { d.sp.material.opacity *= f; d.sh.material.opacity = f; }
      floorMat.opacity = 1 - swing;
    }
    if (s >= REVEAL && !revealed) { revealed = true; o.onLanded && o.onLanded(); }
    if (revealed) {
      const p = clamp((s - REVEAL) / FADE);
      container.style.opacity = String(1 - easeInOut(p));
      pageEls.forEach((el, n) => { const q = easeOut(clamp((s - REVEAL - n * 0.05) / 0.55)); el.style.transform = q < 1 ? 'translateY(' + (1 - q) * 24 + 'px)' : ''; });
      if (p >= 1 && s >= REVEAL + 0.55) { stop(); onDone(); return; }
    }
    renderer.render(scene, cam);
    requestAnimationFrame(frame);
  }
  function stop() {
    stopped = true;
    pageEls.forEach((el) => (el.style.transform = ''));
    renderer.dispose();
  }
  // Erst starten, wenn die Schrift für die Beschriftungen bereit ist
  const fonts = document.fonts ? Promise.all([document.fonts.load('600 58px Geist'), document.fonts.load('400 42px Geist')]).catch(() => {}) : Promise.resolve();
  return fonts.then(() => {
    units.forEach((u) => {
      u.idle.material.map = texOf(u.m, { state: 'idle' });
      u.lit.material.map = texOf(u.m, { state: 'active' });
      u.done = texOf(u.m, { state: 'done' });
      u.bare.material.map = texOf(u.m, { state: 'done', bare: true });
    });
    t0 = performance.now();
    requestAnimationFrame(frame);
    return { stop, duration: REVEAL + 0.55 };
  });
}

// ---------- Hilfen ----------
function clamp(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
function smooth(v) { v = clamp(v); return v * v * (3 - 2 * v); }
function easeInOut(v) { return v < 0.5 ? 4 * v * v * v : 1 - Math.pow(-2 * v + 2, 3) / 2; }
function easeOut(v) { return 1 - Math.pow(1 - v, 3); }

function mix(a, b, t) {
  const parse = (c) => (c[0] === '#' ? [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16)) : c.match(/\d+/g).slice(0, 3).map(Number));
  const pa = parse(a), pb = parse(b);
  return 'rgb(' + pa.map((v, i) => Math.round(v + (pb[i] - v) * t)).join(',') + ')';
}

function shadowTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d');
  const s = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  s.addColorStop(0, 'rgba(20,30,40,0.34)'); s.addColorStop(0.55, 'rgba(20,30,40,0.14)'); s.addColorStop(1, 'rgba(20,30,40,0)');
  g.fillStyle = s; g.fillRect(0, 0, 128, 128);
  return new CanvasTexture(c);
}

// Kugel: Licht oben links, Eigenschatten unten rechts, Aufhellung vom Boden, weicher Glanzpunkt
function ballTexture(col, aniso) {
  const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
  const C = 128, R = 125, hex = (x) => '#' + x.getHexString();
  const lit = col.clone().lerp(new Color('#ffffff'), 0.45), dark = col.clone().multiplyScalar(0.62), rim = col.clone().multiplyScalar(0.8);
  g.beginPath(); g.arc(C, C, R, 0, Math.PI * 2); g.clip();
  const body = g.createRadialGradient(C - 40, C - 48, 10, C - 10, C - 12, R * 1.12);
  body.addColorStop(0, hex(lit)); body.addColorStop(0.45, hex(col)); body.addColorStop(0.88, hex(dark)); body.addColorStop(1, hex(dark));
  g.fillStyle = body; g.fillRect(0, 0, 256, 256);
  const bounce = g.createRadialGradient(C + 20, C + 165, 30, C + 20, C + 165, 100);
  bounce.addColorStop(0, hex(rim) + 'aa'); bounce.addColorStop(1, hex(rim) + '00'); g.fillStyle = bounce; g.fillRect(0, 0, 256, 256);
  const spec = g.createRadialGradient(C - 42, C - 52, 0, C - 42, C - 52, 35);
  spec.addColorStop(0, 'rgba(255,255,255,0.85)'); spec.addColorStop(0.5, 'rgba(255,255,255,0.25)'); spec.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = spec; g.fillRect(0, 0, 256, 256);
  const t = new CanvasTexture(c); t.colorSpace = SRGBColorSpace; t.minFilter = LinearMipmapLinearFilter; t.anisotropy = aniso;
  return t;
}

// Gewölbte Fläche mit derselben Lichtführung wie die Kugeln. k = Stärke (blasse Module weniger plastisch)
function sphereFill(g, cx, cy, r, base, k = 1) {
  const lit = mix(base, '#ffffff', 0.42 * k), dark = mix(base, '#000000', 0.34 * k);
  g.save(); g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.clip();
  const body = g.createRadialGradient(cx - r * 0.32, cy - r * 0.38, r * 0.08, cx - r * 0.08, cy - r * 0.1, r * 1.12);
  body.addColorStop(0, lit); body.addColorStop(0.45, base); body.addColorStop(0.9, dark); body.addColorStop(1, dark);
  g.fillStyle = body; g.fillRect(cx - r, cy - r, 2 * r, 2 * r);
  const sp = g.createRadialGradient(cx - r * 0.34, cy - r * 0.42, 0, cx - r * 0.34, cy - r * 0.42, r * 0.34);
  sp.addColorStop(0, `rgba(255,255,255,${0.7 * k})`); sp.addColorStop(0.5, `rgba(255,255,255,${0.2 * k})`); sp.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = sp; g.fillRect(cx - r, cy - r, 2 * r, 2 * r);
  g.restore();
}
function floorShadow(g, cx, cy, rx, ry, a) {
  g.save(); g.translate(cx, cy); g.scale(1, ry / rx);
  const s = g.createRadialGradient(0, 0, 0, 0, 0, rx);
  s.addColorStop(0, `rgba(20,30,40,${a})`); s.addColorStop(0.55, `rgba(20,30,40,${a * 0.4})`); s.addColorStop(1, 'rgba(20,30,40,0)');
  g.fillStyle = s; g.beginPath(); g.arc(0, 0, rx, 0, Math.PI * 2); g.fill(); g.restore();
}
// Symbol aus den gemeinsamen Pfaden (64er-Raster wie im Kopfbereich der Seite)
function drawGlyph(g, layers, color, cx, cy, R) {
  const col = { fg: '#fff', bg: color, light: mix(color, '#ffffff', 0.55) };
  g.save(); g.translate(cx - R, cy - R); g.scale(R / 32, R / 32); g.lineCap = 'round'; g.lineJoin = 'round';
  for (const l of layers) {
    const p = new Path2D(l.d);
    if (l.fill) { g.fillStyle = col[l.fill]; g.fill(p); } else { g.strokeStyle = col[l.stroke]; g.lineWidth = l.w; g.stroke(p); }
  }
  g.restore();
}

// Modul im Make-Look: Halbmond-Anschlüsse, gewölbte Farbscheibe, Symbol, Name + Nummer, Aktion
function moduleCanvas(m, st, GLYPHS) {
  const c = document.createElement('canvas'); c.width = 640; c.height = 640;
  const g = c.getContext('2d'); const cx = 320, cy = 250, R = 150;
  const idle = st.state === 'idle', k3 = idle ? 0.45 : 1;
  const col = idle ? mix(m.color, P.idleMix, 0.72) : m.color;
  const bare = !!st.bare;          // wie im Kopfbereich: kein Schein, kein Lichtrand, keine Beschriftung
  if (!idle && !bare) {            // Aufleuchten: kräftiger Farbschein
    const gl = g.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * 1.9); gl.addColorStop(0, m.color + 'aa'); gl.addColorStop(1, m.color + '00');
    g.fillStyle = gl; g.fillRect(0, 0, 640, 640);
  }
  floorShadow(g, cx + 22, cy + R + 16, R * 1.05, R * 0.2, idle ? 0.1 : 0.22);
  const conn = idle ? mix(m.color, P.idleMix, 0.8) : mix(m.color, '#1c1f23', 0.3);
  for (const [x, a0, a1, ccw] of [[cx - R - 18, Math.PI / 2, -Math.PI / 2, true], [cx + R + 18, -Math.PI / 2, Math.PI / 2, false]]) {
    const cg = g.createLinearGradient(x, cy - 48, x + 10, cy + 48);
    cg.addColorStop(0, mix(conn, '#ffffff', 0.3 * k3)); cg.addColorStop(1, mix(conn, '#000000', 0.25 * k3));
    g.fillStyle = cg; g.beginPath(); g.arc(x, cy, 48, a0, a1, ccw); g.closePath(); g.fill();
  }
  if (!idle && !bare) { g.save(); g.shadowColor = m.color + '66'; g.shadowBlur = 60; g.beginPath(); g.arc(cx, cy, R - 2, 0, 7); g.fillStyle = col; g.fill(); g.restore(); }
  sphereFill(g, cx, cy, R, idle || bare ? col : mix(m.color, '#ffffff', 0.08), k3);
  if (!idle && !bare) {            // gläserner Lichtrand
    const rg = g.createLinearGradient(cx - R, cy - R, cx + R, cy + R); rg.addColorStop(0, 'rgba(255,255,255,0.95)'); rg.addColorStop(1, 'rgba(255,255,255,0.35)');
    g.lineWidth = 9; g.strokeStyle = rg; g.beginPath(); g.arc(cx, cy, R - 5, 0, 7); g.stroke();
  }
  const layers = GLYPHS[m.icon];
  if (layers) {
    g.save(); g.shadowColor = idle ? 'rgba(0,0,0,0.06)' : 'rgba(0,0,0,0.22)'; g.shadowBlur = 10; g.shadowOffsetX = 4; g.shadowOffsetY = 7;
    drawGlyph(g, layers, idle ? col : m.color, cx, cy, R); g.restore();
  }
  if (m.trigger) {                 // Uhr am Auslöser
    const x = cx - R * 0.72, y = cy + R * 0.72;
    floorShadow(g, x + 6, y + 50, 50, 10, 0.18);
    sphereFill(g, x, y, 50, idle ? '#eef0f2' : mix(m.color, '#ffffff', 0.55), k3);
    g.beginPath(); g.arc(x, y, 50, 0, 7); g.lineWidth = 7; g.strokeStyle = idle ? '#fff' : m.color; g.stroke();
    g.beginPath(); g.arc(x, y, 34, 0, 7); g.fillStyle = '#fff'; g.fill();
    g.strokeStyle = '#6b7280'; g.lineWidth = 6; g.lineCap = 'round'; g.beginPath(); g.moveTo(x, y); g.lineTo(x + 18, y + 12); g.moveTo(x, y); g.lineTo(x - 4, y - 22); g.stroke();
  }
  if (st.state === 'done') {       // „1“ nach getaner Arbeit
    const x = cx + R * 0.8, y = cy - R * 0.8;
    g.save(); g.shadowColor = 'rgba(11,122,75,0.35)'; g.shadowBlur = 14;
    g.beginPath(); g.arc(x, y, 42, 0, 7); g.fillStyle = ACCENT; g.fill(); g.restore();
    sphereFill(g, x, y, 42, ACCENT);
    g.beginPath(); g.arc(x, y, 42, 0, 7); g.lineWidth = 8; g.strokeStyle = '#fff'; g.stroke();
    g.fillStyle = '#0b1f16'; g.font = '600 48px Geist, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('1', x, y + 2);
  }
  if (bare) return c;
  // Beschriftung auf heller Fläche: die Kette läuft dahinter durch
  g.textBaseline = 'alphabetic';
  g.font = '400 42px Geist, sans-serif'; const aw = g.measureText(m.action).width;
  g.font = '600 58px Geist, sans-serif';
  const nameW = g.measureText(m.app).width, bw = 54, total = nameW + 14 + bw, x0 = cx - total / 2;
  const pw = Math.min(620, Math.max(total, aw) + 40);
  g.save(); g.shadowColor = DARK ? 'rgba(0,0,0,0.5)' : 'rgba(20,30,40,0.12)'; g.shadowBlur = 22; g.shadowOffsetY = 6; g.fillStyle = P.plate;
  g.beginPath(); roundRect(g, cx - pw / 2, 440, pw, 140, 22); g.fill(); g.restore();
  g.fillStyle = idle ? P.nameIdle : P.name; g.textAlign = 'left'; g.fillText(m.app, x0, 500);
  g.fillStyle = idle ? P.badgeIdle : P.badge; g.beginPath(); roundRect(g, x0 + nameW + 14, 452, bw, 58, 10); g.fill();
  g.fillStyle = idle ? P.nrIdle : P.nr; g.font = '600 38px Geist, sans-serif'; g.textAlign = 'center'; g.fillText(String(m.nr), x0 + nameW + 14 + bw / 2, 494);
  g.font = '400 42px Geist, sans-serif'; g.fillText(m.action, cx, 562);
  return c;
}
function roundRect(g, x, y, w, h, r) {
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}
