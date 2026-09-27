// 4ELEMENTS – 3D-Intro (Quelle). Wird mit `npm run build:intro3d` zu assets/js/intro3d.js gebündelt.
// Echte 3D-Szene (Three.js): Der Workflow steht auf einem Boden, die Kamera fährt auf Augenhöhe ohne Anhalten
// durch das Szenario. Jedes Modul arbeitet nacheinander (Ring im Uhrzeigersinn, dann „1“), die Routen des
// Routers laufen wie in Make nacheinander. Am Ende steigt die Kamera in die Übersicht auf, die vier Module
// des Kopfbereichs gleiten exakt an ihren Platz in der Seite, dann erscheint die Seite.
import {
  WebGLRenderer, Scene, Fog, PerspectiveCamera, Sprite, SpriteMaterial, CanvasTexture, InstancedMesh,
  CircleGeometry, MeshBasicMaterial, PlaneGeometry, Mesh, SphereGeometry, CubicBezierCurve3, CatmullRomCurve3,
  Vector3, Object3D, Raycaster, Plane, Vector2, RepeatWrapping, SRGBColorSpace,
} from 'three';

const ACCENT = '#3ddc97';
// Welt: x = Fahrtrichtung, z = seitlich. Rolle der 9 Module wie im Intro-Datenblock.
const P = [[0, 0], [4, 0], [7.4, 0], [11, -4], [15, -4], [11, 0], [15, 0], [11, 4], [15, 4]];

export function run(o) {
  const { container, mods: MODS, icons: ICONS, links: LINKS, portrait, onDone } = o;
  const W = window.innerWidth, H = window.innerHeight;
  const clock = () => (typeof window.__introClock === 'function' ? window.__introClock() : (performance.now() - t0) / 1000);

  // ---------- Renderer ----------
  const renderer = new WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(W, H);
  renderer.setClearColor(0xffffff);
  renderer.outputColorSpace = SRGBColorSpace;
  const canvas = renderer.domElement;
  canvas.className = 'intro__canvas';
  container.appendChild(canvas);
  const scene = new Scene();
  scene.fog = new Fog(0xffffff, 8, 30);

  // ---------- Boden ----------
  const dc = document.createElement('canvas'); dc.width = dc.height = 64;
  const dg = dc.getContext('2d');
  dg.fillStyle = '#fff'; dg.fillRect(0, 0, 64, 64); dg.fillStyle = '#b3bac1';
  dg.beginPath(); dg.arc(32, 32, 3.2, 0, 7); dg.fill();
  const ftex = new CanvasTexture(dc); ftex.wrapS = ftex.wrapT = RepeatWrapping; ftex.repeat.set(220, 220);
  ftex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const floorMat = new MeshBasicMaterial({ map: ftex, transparent: true });
  const floor = new Mesh(new PlaneGeometry(160, 160), floorMat);
  floor.rotation.x = -Math.PI / 2; floor.position.set(7, 0, 0); scene.add(floor);

  // ---------- Verbindungen: gepunktet, werden beim Durchlauf grün ----------
  const dotGeo = new CircleGeometry(1, 12);
  const greyMat = new MeshBasicMaterial({ color: 0xaab2ba, transparent: true });
  const greenMat = new MeshBasicMaterial({ color: ACCENT, transparent: true });
  const tmp = new Object3D();
  const links = LINKS.map(([a, b]) => {
    const A = P[a], B = P[b], mx = (A[0] + B[0]) / 2;
    const curve = new CubicBezierCurve3(new Vector3(A[0], 0.03, A[1]), new Vector3(mx, 0.03, A[1]), new Vector3(mx, 0.03, B[1]), new Vector3(B[0], 0.03, B[1]));
    const n = Math.round(curve.getLength() / 0.28);
    const grey = new InstancedMesh(dotGeo, greyMat, n - 1), green = new InstancedMesh(dotGeo, greenMat, n - 1);
    for (let i = 1; i < n; i++) {
      const p = curve.getPointAt(i / n);
      tmp.position.copy(p); tmp.rotation.set(-Math.PI / 2, 0, 0);
      tmp.scale.setScalar(0.06); tmp.updateMatrix(); grey.setMatrixAt(i - 1, tmp.matrix);
      tmp.position.y = 0.035; tmp.scale.setScalar(0.078); tmp.updateMatrix(); green.setMatrixAt(i - 1, tmp.matrix);
    }
    green.count = 0;
    scene.add(grey, green);
    return { curve, n: n - 1, grey, green };
  });

  // ---------- Datenpaket mit Schweif ----------
  const packet = [];
  for (let j = 0; j < 6; j++) {
    const m = new Mesh(new SphereGeometry(0.16 - j * 0.02, 16, 12), new MeshBasicMaterial({ color: ACCENT, transparent: true, opacity: 1 - j * 0.15 }));
    m.visible = false; scene.add(m); packet.push(m);
  }
  const halo = new Sprite(new SpriteMaterial({ map: glowTex(), transparent: true, depthWrite: false }));
  halo.scale.set(1.3, 1.3, 1); halo.visible = false; scene.add(halo);

  // ---------- Module: stehende Tafeln, die zur Kamera schauen ----------
  const units = MODS.map((m, i) => {
    const k = m.router ? 1.5 : 2.2, h = k * 1.25;
    const tex = (st) => { const t = new CanvasTexture(moduleCanvas(m, st, ICONS)); t.colorSpace = SRGBColorSpace; t.anisotropy = 8; return t; };
    const base = tex({}), done = m.router ? base : tex({ done: true }), bare = m.router ? base : tex({ done: true, noLabel: true });
    const mat = new SpriteMaterial({ map: base, transparent: true, fog: true });
    const sp = new Sprite(mat); sp.scale.set(k, h, 1);
    sp.position.set(P[i][0], h / 2, P[i][1]); scene.add(sp);
    // Fortschrittsring als eigene Tafel über dem Kreis
    const rc = document.createElement('canvas'); rc.width = rc.height = 256;
    const rtex = new CanvasTexture(rc); rtex.colorSpace = SRGBColorSpace;
    const ring = new Sprite(new SpriteMaterial({ map: rtex, transparent: true, depthTest: false, fog: true }));
    const circleY = h / 2 + (90 / 640) * h;             // Kreismitte (Canvas y=230 von 640)
    const rs = (400 / 512) * k; ring.scale.set(rs, rs, 1); ring.position.set(P[i][0], circleY, P[i][1]); ring.visible = false; scene.add(ring);
    return { m, sp, mat, base, done, bare, k, h, ring, rc, rtex, circleY, isDone: false, drawn: -1 };
  });
  function drawRing(u, p) {
    if (Math.abs(u.drawn - p) < 0.012) return;
    const g = u.rc.getContext('2d'); g.clearRect(0, 0, 256, 256);
    g.lineWidth = 8; g.lineCap = 'round';
    g.beginPath(); g.arc(128, 128, 118, 0, 7); g.strokeStyle = 'rgba(61,220,151,0.22)'; g.stroke();
    g.beginPath(); g.arc(128, 128, 118, -Math.PI / 2, -Math.PI / 2 + p * Math.PI * 2); g.strokeStyle = ACCENT; g.stroke();
    u.rtex.needsUpdate = true; u.drawn = p;
  }

  // ---------- Ablauf (Sekunden): Module nacheinander, Routen nacheinander ----------
  const seq = [];
  let t = 0.05, wi = 0;
  const WORK = [0.4, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25], LINK = 0.16, ROUTER = 0.05;
  seq.push({ type: 'work', i: 0, t0: t, t1: (t += WORK[wi++]) });
  let last = 0;
  LINKS.forEach(([a, b], k) => {
    if (a !== last && MODS[a].router) seq.push({ type: 'work', i: a, t0: t, t1: (t += ROUTER) });
    seq.push({ type: 'link', k, t0: t, t1: (t += LINK) });
    seq.push({ type: 'work', i: b, t0: t, t1: (t += MODS[b].router ? ROUTER : WORK[wi++] || 0.25) });
    last = b;
  });
  const RUN_END = t;

  // ---------- Kamerafahrt: eine durchgehende Kurve durch die Storyboard-Positionen ----------
  const fovAdd = portrait ? 22 : 0;
  const K = [
    [0.0, [-4.3, 1.6, 1.8], [4, 1.0, -0.4], 54 + fovAdd],
    [0.8, [1.2, 1.6, 2.6], [9, 0.9, -0.8], 54 + fovAdd],
    [1.55, [5.6, 1.7, 3.0], [12.5, 0.9, -2.2], 56 + fovAdd],
    [2.3, [8.6, 1.7, 2.4], [15.5, 0.9, -0.4], 56 + fovAdd],
    [2.95, [8.8, 3.0, 7.6], [14, 0.8, 3.0], 56 + fovAdd],
    [3.35, [9.5, 7.5, 12], [11, 0.5, 1.0], 50 + fovAdd * 0.5],
    [3.8, portrait ? [7.5, 23, 0.001] : [7.5, 15.5, 0.001], [7.5, 0, 0], portrait ? 50 : 42],
  ];
  const posCurve = new CatmullRomCurve3(K.map((k) => new Vector3(...k[1])), false, 'centripetal');
  const lookCurve = new CatmullRomCurve3(K.map((k) => new Vector3(...k[2])), false, 'centripetal');
  const T_END = K[K.length - 1][0];
  const upEnd = portrait ? new Vector3(-1, 0, 0) : new Vector3(0, 0, -1);
  const cam = new PerspectiveCamera(54 + fovAdd, W / H, 0.1, 200);
  function cameraAt(s) {
    s = Math.min(s, T_END);
    let i = 0; while (i < K.length - 2 && s > K[i + 1][0]) i++;
    let f = (s - K[i][0]) / (K[i + 1][0] - K[i][0]);
    if (i === K.length - 2) f = 1 - Math.pow(1 - f, 3); // weich in die Übersicht auslaufen
    const u = (i + f) / (K.length - 1);
    cam.position.copy(posCurve.getPoint(u));
    const fov = K[i][3] + (K[i + 1][3] - K[i][3]) * f;
    cam.fov = fov; cam.updateProjectionMatrix();
    const b = smooth((s - 3.05) / 0.75);
    cam.up.set(0, 1, 0).lerp(upEnd, b).normalize();
    cam.lookAt(lookCurve.getPoint(u));
  }

  // ---------- Übergabe: Zielpositionen der Module im Kopfbereich ----------
  const HAND = T_END + 0.3, GLIDE = 0.45, STAG = 0.04;   // Übersicht kurz stehen lassen
  const heroIdx = MODS.map((m, i) => (m.hero ? i : -1)).filter((i) => i > -1);
  const heroBodies = o.heroBodies;
  let targets = null;
  function computeTargets() {
    cameraAt(T_END); cam.updateMatrixWorld();
    const ray = new Raycaster(), v = new Vector2();
    targets = heroIdx.map((i, h) => {
      const u = units[i], r = heroBodies[h] && heroBodies[h].getBoundingClientRect();
      if (!r) return null;
      const plane = new Plane(new Vector3(0, 1, 0), -u.circleY);
      v.set(((r.left + r.width / 2) / W) * 2 - 1, -((r.top + r.height / 2) / H) * 2 + 1);
      ray.setFromCamera(v, cam);
      const hit = new Vector3(); ray.ray.intersectPlane(plane, hit);
      const dist = -hit.clone().applyMatrix4(cam.matrixWorldInverse).z;   // Tiefe entlang der Blickrichtung
      const wpp = (2 * dist * Math.tan((cam.fov * Math.PI) / 360)) / H;   // Welteinheiten pro Bildpunkt
      const k = (r.width * wpp) / (300 / 512);                             // Kreis = 300 von 512 px der Tafel
      return { circle: hit, k };
    });
  }

  // ---------- Seite erscheint ----------
  const REVEAL = HAND + GLIDE + STAG * 3 + 0.02;
  const pageEls = o.pageEls || [];
  let revealed = false;

  // ---------- Bildschleife ----------
  let t0 = performance.now(), stopped = false;
  function frame() {
    if (stopped || !canvas.isConnected) return;
    const s = clock();
    cameraAt(s);
    // Module, Ringe, Pakete
    packet.forEach((m) => (m.visible = false)); halo.visible = false;
    units.forEach((u) => (u.ring.visible = false));
    for (const e of seq) {
      if (e.type === 'link') {
        const L = links[e.k], p = clamp((s - e.t0) / (e.t1 - e.t0));
        L.green.count = Math.floor(p * L.n);
        if (s >= e.t0 && s < e.t1) {
          const q = easeInOut(p);
          packet.forEach((m, j) => { const pt = L.curve.getPointAt(clamp(q - j * 0.035)); m.position.set(pt.x, 0.2, pt.z); m.visible = true; });
          halo.position.copy(packet[0].position); halo.visible = true;
        }
      } else {
        const u = units[e.i];
        if (u.m.router) {
          const p = clamp((s - e.t0) / 0.2); const b = 1 + 0.15 * Math.sin(Math.PI * p);
          if (s >= e.t0 && p < 1) u.sp.scale.set(u.k * b, u.h * b, 1);
          continue;
        }
        if (s >= e.t0 && s < e.t1) { u.ring.visible = true; drawRing(u, (s - e.t0) / (e.t1 - e.t0)); }
        const done = s >= e.t1;
        if (done !== u.isDone) { u.isDone = done; u.mat.map = done ? u.done : u.base; u.mat.needsUpdate = true; }
        const pop = clamp((s - e.t1) / 0.3);
        const b = done && pop < 1 ? 1 + 0.08 * Math.sin(Math.PI * pop) : 1;
        if (s < HAND) u.sp.scale.set(u.k * b, u.h * b, 1);
      }
    }
    // Übergabe
    if (s >= HAND - 0.15) {
      const fade = 1 - clamp((s - (HAND - 0.15)) / 0.3);
      greyMat.opacity = greenMat.opacity = fade; floorMat.opacity = fade;
      if (!targets) computeTargets();
      units.forEach((u, i) => {
        const h = heroIdx.indexOf(i);
        if (h < 0 || !targets[h]) { u.mat.opacity = fade; return; }
        if (portrait && u.mat.map !== u.bare && s >= HAND) { u.mat.map = u.bare; u.mat.needsUpdate = true; }
        const p = easeInOut(clamp((s - HAND - h * STAG) / GLIDE)), T = targets[h];
        const k = u.k + (T.k - u.k) * p, hh = k * 1.25;
        // Kreismitte liegt auf der Tafel oberhalb der Mitte – „oben“ ist in der Draufsicht die Bildschirm-Oberkante (upEnd)
        const c0 = new Vector3(P[i][0], u.h / 2, P[i][1]).addScaledVector(upEnd, (90 / 640) * u.h);
        const c = c0.lerp(T.circle, p);
        u.sp.scale.set(k, hh, 1);
        u.sp.position.copy(c).addScaledVector(upEnd, -(90 / 640) * hh);
      });
    }
    if (s >= REVEAL && !revealed) { revealed = true; o.onLanded && o.onLanded(); }
    if (revealed) {
      const p = clamp((s - REVEAL) / 0.35);
      container.style.opacity = String(1 - p);
      pageEls.forEach((el, n) => { const q = easeOut(clamp((s - REVEAL - n * 0.05) / 0.55)); el.style.transform = q < 1 ? 'translateY(' + (1 - q) * 24 + 'px)' : ''; });
      if (p >= 1 && s >= REVEAL + 0.7) { stop(); onDone(); return; }
    }
    renderer.render(scene, cam);
    requestAnimationFrame(frame);
  }
  function stop() {
    stopped = true;
    pageEls.forEach((el) => (el.style.transform = ''));
    renderer.dispose();
  }
  // Erst rendern, wenn Schriften für die Beschriftungen bereit sind
  const fonts = document.fonts ? Promise.all([document.fonts.load('600 60px Inter'), document.fonts.load('400 46px Inter')]).catch(() => {}) : Promise.resolve();
  return fonts.then(() => {
    units.forEach((u) => {
      if (u.m.router) return;
      u.base.image = moduleCanvas(u.m, {}, ICONS); u.base.needsUpdate = true;
      u.done.image = moduleCanvas(u.m, { done: true }, ICONS); u.done.needsUpdate = true;
      u.bare.image = moduleCanvas(u.m, { done: true, noLabel: true }, ICONS); u.bare.needsUpdate = true;
    });
    t0 = performance.now();
    requestAnimationFrame(frame);
    return { stop, duration: REVEAL + 0.7 };
  });
}

// ---------- Hilfen ----------
function clamp(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
function smooth(v) { v = clamp(v); return v * v * (3 - 2 * v); }
function easeInOut(v) { return v < 0.5 ? 4 * v * v * v : 1 - Math.pow(-2 * v + 2, 3) / 2; }
function easeOut(v) { return 1 - Math.pow(1 - v, 3); }

function glowTex() {
  const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d');
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64); gr.addColorStop(0, 'rgba(61,220,151,0.8)'); gr.addColorStop(1, 'rgba(61,220,151,0)');
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128); return new CanvasTexture(c);
}

function shade(hex, pct) {
  const n = parseInt(hex.slice(1), 16);
  const f = (v) => Math.max(0, Math.min(255, Math.round(v + (pct / 100) * (pct > 0 ? 255 - v : v))));
  return 'rgb(' + f(n >> 16) + ',' + f((n >> 8) & 255) + ',' + f(n & 255) + ')';
}

// Modul im Make-Stil als Bild: Farbschein, weißer Rand, glänzende Farbscheibe, Symbol, „1“, Beschriftung
function moduleCanvas(m, st, ICONS) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 640;
  const g = c.getContext('2d'); const cx = 256, cy = 230, R = m.router ? 90 : 150;
  const glow = g.createRadialGradient(cx, cy + R * 0.6, 10, cx, cy + R * 0.6, R * 1.5);
  glow.addColorStop(0, m.color + '88'); glow.addColorStop(1, m.color + '00');
  g.fillStyle = glow; g.fillRect(0, 0, 512, 640);
  g.save(); g.shadowColor = 'rgba(28,31,35,0.28)'; g.shadowBlur = 40; g.shadowOffsetY = 18;
  g.beginPath(); g.arc(cx, cy, R + 16, 0, 7); g.fillStyle = '#fff'; g.fill(); g.restore();
  g.beginPath(); g.arc(cx, cy, R + 16, 0, 7); g.strokeStyle = 'rgba(28,31,35,0.08)'; g.lineWidth = 3; g.stroke();
  const disc = g.createRadialGradient(cx - R * 0.35, cy - R * 0.45, R * 0.1, cx, cy, R * 1.05);
  disc.addColorStop(0, shade(m.color, 45)); disc.addColorStop(0.55, m.color); disc.addColorStop(1, shade(m.color, -25));
  g.beginPath(); g.arc(cx, cy, R, 0, 7); g.fillStyle = disc; g.fill();
  g.save(); const s = (R * 1.1) / 24; g.translate(cx - 12 * s, cy - 12 * s); g.scale(s, s);
  g.strokeStyle = '#fff'; g.lineWidth = 1.7; g.lineCap = 'round'; g.lineJoin = 'round';
  const svg = ICONS[m.icon] || '';
  for (const d of [...svg.matchAll(/ d="([^"]+)"/g)].map((x) => x[1])) g.stroke(new Path2D(d));
  for (const r of svg.matchAll(/<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="([\d.]+)"/g)) { g.beginPath(); roundRect(g, +r[1], +r[2], +r[3], +r[4], +r[5]); g.stroke(); }
  for (const r of svg.matchAll(/<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"/g)) { g.beginPath(); g.arc(+r[1], +r[2], +r[3], 0, 7); g.stroke(); }
  g.restore();
  if (m.trigger) {
    g.save(); g.shadowColor = 'rgba(28,31,35,0.2)'; g.shadowBlur = 10;
    g.beginPath(); g.arc(cx - R * 0.78, cy + R * 0.78, 34, 0, 7); g.fillStyle = '#fff'; g.fill(); g.restore();
    g.strokeStyle = '#1c1f23'; g.lineWidth = 5; g.beginPath(); g.arc(cx - R * 0.78, cy + R * 0.78, 18, 0, 7); g.stroke();
    g.beginPath(); g.moveTo(cx - R * 0.78, cy + R * 0.78 - 10); g.lineTo(cx - R * 0.78, cy + R * 0.78); g.lineTo(cx - R * 0.78 + 7, cy + R * 0.78 + 5); g.stroke();
  }
  if (st.done && !m.router) {
    g.save(); g.shadowColor = 'rgba(11,122,75,0.35)'; g.shadowBlur = 14;
    g.beginPath(); g.arc(cx + R * 0.82, cy - R * 0.82, 44, 0, 7); g.fillStyle = ACCENT; g.fill(); g.restore();
    g.lineWidth = 9; g.strokeStyle = '#fff'; g.stroke();
    g.fillStyle = '#0b1f16'; g.font = '600 52px Inter, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText('1', cx + R * 0.82, cy - R * 0.82 + 3);
  }
  if (!m.router && !st.noLabel) {
    g.textAlign = 'center'; g.textBaseline = 'alphabetic';
    g.fillStyle = '#1c1f23'; g.font = '600 60px Inter, sans-serif'; g.fillText(m.app, cx, 505);
    g.fillStyle = '#525961'; g.font = '400 46px Inter, sans-serif'; g.fillText(m.action, cx, 565);
  }
  return c;
}
function roundRect(g, x, y, w, h, r) {
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}
