// Baut die statische Website aus den Inhaltsdateien in content/ nach dist/.
// Aufruf: npm run build   (keine Abhängigkeiten, nur Node.js >= 18)

import { readFileSync, writeFileSync, mkdirSync, rmSync, cpSync, readdirSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(fileURLToPath(import.meta.url));
const DIST = join(ROOT, 'dist');
const CONTENT = join(ROOT, 'content');
const LANGS = ['de', 'en'];

// ---------- Inhalte laden ----------

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (err) {
    console.error(`\nFehler in ${path.replace(ROOT + '/', '')}:\n  ${err.message}\n`);
    console.error('Tipp: Fehlt ein Komma oder ein Anführungszeichen?');
    process.exit(1);
  }
}

const site = readJson(join(CONTENT, 'site.json'));
const t = Object.fromEntries(LANGS.map((l) => [l, readJson(join(CONTENT, `${l}.json`))]));

const useCaseDir = join(CONTENT, 'anwendungsfaelle');
const useCases = readdirSync(useCaseDir)
  .filter((f) => f.endsWith('.json'))
  .map((f) => ({ file: f, ...readJson(join(useCaseDir, f)) }))
  .sort((a, b) => (a.order ?? 99) - (b.order ?? 99));

for (const uc of useCases) {
  for (const l of LANGS) {
    if (!uc[l]?.slug) throw new Error(`${uc.file}: "${l}.slug" fehlt`);
    if (!/^[a-z0-9-]+$/.test(uc[l].slug)) {
      throw new Error(`${uc.file}: Slug "${uc[l].slug}" darf nur a–z, 0–9 und Bindestriche enthalten (keine Umlaute)`);
    }
  }
}
const publishedUseCases = useCases.filter((uc) => uc.published);

// ---------- Routen (eine Seite = ein Eintrag mit Pfad je Sprache) ----------

const routes = {
  home: { de: '/', en: '/en/' },
  imprint: { de: '/impressum/', en: '/en/legal-notice/' },
  privacy: { de: '/datenschutz/', en: '/en/privacy/' },
  useCases: { de: '/anwendungsfaelle/', en: '/en/use-cases/' },
};
const ucPath = (uc, l) => (l === 'de' ? `/${uc.de.slug}/` : `/en/${uc.en.slug}/`);

// ---------- Hilfsfunktionen ----------

const esc = (s = '') =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const mailto = (subject) => `mailto:${site.email}?subject=${encodeURIComponent(subject)}`;

function assetHash(rel) {
  return createHash('sha256').update(readFileSync(join(ROOT, rel))).digest('hex').slice(0, 10);
}
const cssUrl = `/assets/css/style.css?v=${assetHash('assets/css/style.css')}`;
const jsUrl = `/assets/js/main.js?v=${assetHash('assets/js/main.js')}`;
const introJsUrl = `/assets/js/intro.js?v=${assetHash('assets/js/intro.js')}`;
let introAsset;
function introStyles() {
  if (!introAsset) {
    const css = readFileSync(join(ROOT, 'assets/css/intro.css'), 'utf8') + introCss();
    introAsset = { css, url: `/assets/css/intro.css?v=${createHash('sha256').update(css).digest('hex').slice(0, 10)}` };
  }
  return introAsset;
}

// Liest Breite/Höhe aus einer WebP-Datei (für width/height-Attribute gegen Layout-Verschiebungen).
function webpSize(file) {
  const b = readFileSync(file);
  if (b.toString('ascii', 0, 4) !== 'RIFF' || b.toString('ascii', 8, 12) !== 'WEBP') {
    throw new Error(`${file} ist keine WebP-Datei`);
  }
  const chunk = b.toString('ascii', 12, 16);
  if (chunk === 'VP8X') return { w: 1 + b.readUIntLE(24, 3), h: 1 + b.readUIntLE(27, 3) };
  if (chunk === 'VP8 ') return { w: b.readUInt16LE(26) & 0x3fff, h: b.readUInt16LE(28) & 0x3fff };
  if (chunk === 'VP8L') {
    const bits = b.readUInt32LE(21);
    return { w: (bits & 0x3fff) + 1, h: ((bits >> 14) & 0x3fff) + 1 };
  }
  throw new Error(`${file}: unbekanntes WebP-Format`);
}

function image(fileName, alt, cls, { eager = false } = {}) {
  const path = join(ROOT, 'assets/img', fileName);
  if (!existsSync(path)) throw new Error(`Bild nicht gefunden: assets/img/${fileName}`);
  const { w, h } = webpSize(path);
  return `<img class="${cls}" src="/assets/img/${esc(fileName)}" alt="${esc(alt)}" width="${w}" height="${h}" ${
    eager ? 'fetchpriority="high"' : 'loading="lazy"'
  } decoding="async">`;
}

// Ablauf-Grafik: Kreise, verbunden durch gepunktete Linien.
function flow(steps, label, variant) {
  return `<figure class="flow flow--${variant}">
  <ol class="flow__list" aria-label="${esc(label)}">
${steps
  .map(
    (s, i) => `    <li class="flow__step"><span class="flow__node" aria-hidden="true">${String(i + 1).padStart(2, '0')}</span><span class="flow__label">${esc(s)}</span></li>`
  )
  .join('\n')}
  </ol>
</figure>`;
}

// Symbole für die Module (24er-Raster, weiße Linien) – eigene, schlichte Zeichnungen, keine Markenlogos.
const ICONS = {
  bag: '<path d="M6 8h12l-1 12H7L6 8z"/><path d="M9 8V6.5a3 3 0 0 1 6 0V8"/>',
  sheet: '<rect x="4.5" y="4" width="15" height="16" rx="2"/><path d="M4.5 9.5h15M4.5 14.5h15M10 4v16"/>',
  check: '<path d="M12 3l7 3v5c0 4.6-3 7.8-7 10-4-2.2-7-5.4-7-10V6l7-3z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
  filter: '<path d="M4 5h16l-6.2 7.2V18L10.2 20v-7.8L4 5z"/>',
  mail: '<rect x="3.5" y="6" width="17" height="12.5" rx="2"/><path d="M4 7.5l8 6 8-6"/>',
  bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15L6 16.5z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  cart: '<path d="M3 4.5h2.2l2.3 10.5h10l2.2-7.5H6.4"/><circle cx="9" cy="19" r="1.3"/><circle cx="16.5" cy="19" r="1.3"/>',
  doc: '<path d="M7 3.5h7l4.5 4.5v12.5H7z"/><path d="M14 3.5V8h4.5M10 13h5.5M10 16.5h5.5"/>',
  spark: '<path d="M12 4l1.8 5.2L19 11l-5.2 1.8L12 18l-1.8-5.2L5 11l5.2-1.8L12 4z"/><path d="M18.5 3.5v3M17 5h3"/>',
  chat: '<path d="M4.5 5.5h15v10h-9l-4.5 3.5v-3.5h-1.5z"/><path d="M8.5 10.5h7"/>',
  store: '<path d="M4 9.5l1.5-5h13L20 9.5"/><path d="M4 9.5h16v1.5a2.7 2.7 0 0 1-5.3 0 2.7 2.7 0 0 1-5.4 0A2.7 2.7 0 0 1 4 11z"/><path d="M5.5 13.5V20h13v-6.5"/>',
  pulse: '<path d="M3 12h4l2-5 4 10 2-5h6"/>',
  user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
  box: '<path d="M4 7.5L12 4l8 3.5v9L12 20l-8-3.5z"/><path d="M4 7.5l8 3.5 8-3.5M12 11v9"/>',
  done: '<path d="M6 12.5l4 4 8-9"/>',
  router: '<circle cx="5.5" cy="12" r="2"/><path d="M7.5 12H11l7-6M11 12h7M11 12l7 6"/>',
};

// Nur das Symbol (für die Intro-Kacheln), weiß auf farbiger Kachel.
function bareIcon(icon) {
  if (icon === 'logo') {
    return `<svg class="im__icon" viewBox="0 0 24 24" focusable="false"><text x="12" y="18.5" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="19" font-weight="600" fill="#0b1f16">4</text></svg>`;
  }
  if (!ICONS[icon]) throw new Error(`Unbekanntes Modul-Symbol "${icon}". Erlaubt: logo, ${Object.keys(ICONS).join(', ')}`);
  const stroke = icon === 'done' ? '#0b1f16' : '#fff';
  return `<svg class="im__icon" viewBox="0 0 24 24" focusable="false" fill="none" stroke="${stroke}" stroke-width="${icon === 'done' ? 2.6 : 1.9}" stroke-linecap="round" stroke-linejoin="round">${ICONS[icon]}</svg>`;
}

function moduleIcon(icon, color, cls = 'module__icon') {
  if (icon === 'logo') {
    return `<svg class="${cls}" viewBox="0 0 64 64" focusable="false"><circle cx="32" cy="32" r="32" fill="${esc(color)}"/><text x="32" y="43.5" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="32" font-weight="600" fill="#3ddc97">4</text></svg>`;
  }
  const stroke = icon === 'done' ? '#0b1f16' : '#fff';
  if (!ICONS[icon]) throw new Error(`Unbekanntes Modul-Symbol "${icon}". Erlaubt: ${Object.keys(ICONS).join(', ')}`);
  return `<svg class="${cls}" viewBox="0 0 64 64" focusable="false"><circle cx="32" cy="32" r="32" fill="${esc(color)}"/><g transform="translate(14 14) scale(1.5)" fill="none" stroke="${stroke}" stroke-width="${icon === 'done' ? 2.4 : 1.6}" stroke-linecap="round" stroke-linejoin="round">${ICONS[icon]}</g></svg>`;
}

// Kopfbereich: Module fliegen aus allen Richtungen heran und bilden eine Workflow-Kette.
// Die sichtbare Szene ist dekorativ (aria-hidden); für Screenreader gibt es die Liste darunter.
function heroScene(modules, label) {
  const ghosts = [
    ['cart', '#E47911'], ['doc', '#475569'], ['spark', '#0F766E'], ['chat', '#7C3AED'], ['bell', '#B45309'], ['filter', '#334155'],
  ];
  const chain = modules
    .map((m, i) => {
      const mod = `<div class="module module--${i + 1}">
              <div class="module__body">
                <span class="module__ring"></span>
                ${moduleIcon(m.icon, m.color)}
                ${m.trigger ? '<span class="module__trigger"><svg viewBox="0 0 24 24" focusable="false"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 8v4.5l3 1.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></span>' : ''}
                <span class="module__count">1</span>
              </div>
              <span class="module__app">${esc(m.app)}</span>
              <span class="module__action">${esc(m.action)}</span>
            </div>`;
      const link = i < modules.length - 1 ? `\n            <div class="link link--${i + 1}"><span class="link__pulse"></span></div>` : '';
      return mod + link;
    })
    .join('\n            ');
  return `<div class="scene" aria-hidden="true">
          <div class="scene__grid"></div>
          <div class="scene__ghosts">
            ${ghosts.map(([icon, color], i) => `<span class="ghost ghost--${i + 1}">${moduleIcon(icon, color)}</span>`).join('\n            ')}
          </div>
          <div class="chain">
            ${chain}
          </div>
        </div>
        <ol class="visually-hidden" aria-label="${esc(label)}">
          ${modules.map((m) => `<li>${esc(m.app)}: ${esc(m.action)}</li>`).join('\n          ')}
        </ol>`;
}

// ---------- Intro (nur Startseite, einmal pro Sitzung) ----------
// Module fliegen aus allen Richtungen heran, bilden einen verzweigten Workflow,
// ein Durchlauf startet, dann fliegen sie auseinander und geben die Seite frei.
// Aufbau: 0 Auslöser → 1 Firma → Router → drei Zweige (2→3, 4→5, 6→7) → 8, 9 → 10 Ergebnis.

const INTRO = (() => {
  // Positionen (Kreismittelpunkt) im Querformat, Bühne 75em × 40em
  const land = [[5, 20], [15.5, 20], [34, 7.5], [44, 7.5], [34, 20], [44, 20], [34, 32.5], [44, 32.5], [55, 13.5], [55, 29], [67, 20]];
  const router = [24.5, 20];
  // Hochformat (Smartphone), Bühne 26em × 46em: gleicher Ablauf, von oben nach unten
  const toPortrait = ([x, y]) => [+(13 + (y - 20) * 0.68).toFixed(2), +(3.5 + (x - 5) * 0.63).toFixed(2)];
  const nodes = { land: [...land, router], port: [...land, router].map(toPortrait) }; // Index 11 = Router
  const R = 11;
  const links = [[0, 1], [1, R], [R, 2], [R, 4], [R, 6], [2, 3], [4, 5], [6, 7], [3, 8], [5, 8], [7, 9], [8, 10], [9, 10]];
  const depth = { 0: 0, 1: 1, [R]: 2, 2: 3, 4: 3, 6: 3, 3: 4, 5: 4, 7: 4, 8: 5, 9: 5, 10: 6 };

  // Zeitplan in Sekunden
  const T = { drawStart: 1.7, drawStep: 0.1, runStart: 2.1, runStep: 0.17, burst: 3.45, overlayOut: 3.7 };

  // Reproduzierbarer Zufall, damit jeder Build dieselbe Choreografie erzeugt
  let seed = 4;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
  const between = (a, b) => a + (b - a) * rnd();
  const sign = () => (rnd() < 0.5 ? -1 : 1);
  const f = (n) => +n.toFixed(2);

  const count = land.length + 1;
  const fly = Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * Math.PI * 2 + between(-0.3, 0.3);
    const dist = between(48, 70);
    return {
      delay: f(between(0.05, 0.6)),
      from: `translate3d(${f(Math.cos(angle) * dist)}em, ${f(Math.sin(angle) * dist * 0.75)}em, ${f(between(-110, 45))}em) rotateX(${f(sign() * between(160, 340))}deg) rotateY(${f(sign() * between(180, 360))}deg) rotateZ(${f(sign() * between(20, 70))}deg)`,
    };
  });
  const burst = (layout, w, h) =>
    nodes[layout].map(([x, y]) => {
      const dx = x - w / 2, dy = y - h / 2, len = Math.hypot(dx, dy) || 1;
      const d = between(35, 60);
      return `translate3d(${f((dx / len) * d)}em, ${f((dy / len) * d)}em, ${f(between(60, 110))}em) rotateX(${f(sign() * between(60, 160))}deg) rotateY(${f(sign() * between(60, 180))}deg) rotateZ(${f(sign() * between(10, 50))}deg)`;
    });
  const bursts = { land: burst('land', 75, 40), port: burst('port', 26, 46) };
  const burstDelay = Array.from({ length: count }, () => f(T.burst + between(0, 0.12)));
  return { nodes, R, links, depth, T, fly, bursts, burstDelay };
})();

function introPath([x1, y1], [x2, y2], layout) {
  if (layout === 'land') {
    const mx = f2((x1 + x2) / 2);
    return `M${x1} ${y1}C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`;
  }
  const my = f2((y1 + y2) / 2);
  return `M${x1} ${y1}C${x1} ${my} ${x2} ${my} ${x2} ${y2}`;
}
function f2(n) { return +n.toFixed(2); }

function introColors(lang) {
  return [...t[lang].intro.modules.map((m) => m.color), '#94A3B8']; // Index 11 = Router
}

// Leuchtende, gepunktete Verbindungen auf dem Boden, Farbverlauf von Modul zu Modul.
function introLinks(layout, lang) {
  const { nodes, links, depth, T } = INTRO;
  const colors = introColors(lang);
  const [w, h] = layout === 'land' ? [75, 40] : [26, 46];
  const defs = [], paths = [];
  links.forEach(([a, b], k) => {
    const [p1, p2] = [nodes[layout][a], nodes[layout][b]];
    const d = introPath(p1, p2, layout);
    const id = `${layout}${k + 1}`;
    const run = f2(T.runStart + depth[a] * T.runStep);
    defs.push(`<linearGradient id="g${id}" gradientUnits="userSpaceOnUse" x1="${p1[0]}" y1="${p1[1]}" x2="${p2[0]}" y2="${p2[1]}"><stop offset="0" stop-color="${esc(colors[a])}"/><stop offset="1" stop-color="${esc(colors[b])}"/></linearGradient>
            <mask id="m${id}" maskUnits="userSpaceOnUse" x="-10" y="-10" width="${w + 20}" height="${h + 20}"><path class="intro__reveal il--${k + 1}" d="${d}" pathLength="1"/></mask>`);
    paths.push(`<path class="intro__link" d="${d}" stroke="url(#g${id})" mask="url(#m${id})"/>
          <circle class="intro__packet" r="0.34"><animateMotion dur="${T.runStep}s" begin="${run}s" fill="freeze" path="${d}"/><animate attributeName="opacity" values="0;1;1;0" dur="${T.runStep + 0.05}s" begin="${run}s"/></circle>`);
  });
  return `<svg class="intro__links intro__links--${layout}" viewBox="0 0 ${w} ${h}" focusable="false">
          <defs>
            <filter id="glow${layout}" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="0.28" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            ${defs.join('\n            ')}
          </defs>
          <g filter="url(#glow${layout})">
          ${paths.join('\n          ')}
          </g>
        </svg>`;
}

function introModule(n, icon, label, extra = '') {
  return `<div class="im im--${n}${extra}">
            <span class="im__glow"></span>
            <div class="im__stand">
              <div class="im__tile">${bareIcon(icon)}</div>
              <div class="im__base"><span>${esc(label)}</span></div>
            </div>
          </div>`;
}

function introBlock(lang) {
  const tx = t[lang].intro;
  if (tx.modules.length !== 11) throw new Error(`content/${lang}.json: intro.modules braucht genau 11 Module (aktuell ${tx.modules.length})`);
  const mods = tx.modules.map((m, i) => introModule(i + 1, m.icon, m.app, i === 10 ? ' im--final' : '')).join('\n          ');
  return `<div class="intro" id="intro" aria-hidden="true">
    <div class="intro__light"></div>
    <div class="intro__stage">
      <div class="intro__floor"></div>
      ${introLinks('land', lang)}
      ${introLinks('port', lang)}
      <div class="intro__modules">
          ${mods}
          ${introModule(12, 'router', tx.router || 'Router', ' im--router')}
      </div>
    </div>
  </div>
  <button class="intro__skip" type="button">${esc(tx.skip)} →</button>`;
}

// Erzeugt die positionsabhängigen Intro-Regeln (Positionen, Flugbahnen, Zeitplan).
function introCss() {
  const { nodes, fly, bursts, burstDelay, links, depth, T, R } = INTRO;
  const rules = [];
  const modDepth = (i) => (i === R ? depth[R] : depth[i]);
  for (let i = 0; i < nodes.land.length; i++) {
    const n = i + 1;
    const pulse = f2(T.runStart - T.runStep + modDepth(i) * T.runStep + (i === 0 ? 0 : T.runStep * 0.9));
    rules.push(`.im--${n} { left: ${nodes.land[i][0]}em; top: ${nodes.land[i][1]}em; --from: ${fly[i].from}; --burst: ${bursts.land[i]}; animation-delay: ${fly[i].delay}s, ${burstDelay[i]}s; }`);
    rules.push(`.im--${n} { --c: ${introColors('de')[i]}; }`);
    rules.push(`.im--${n} .im__tile::before, .im--${n} .im__glow { animation-delay: ${pulse}s; }`);
  }
  links.forEach(([a], k) => rules.push(`.intro__reveal.il--${k + 1} { animation-delay: ${f2(T.drawStart + depth[a] * T.drawStep)}s; }`));
  const port = nodes.port.map((p, i) => `  .im--${i + 1} { left: ${p[0]}em; top: ${p[1]}em; --burst: ${bursts.port[i]}; }`);
  return `\n/* ---- generiert von build.mjs ---- */\n${rules.join('\n')}\n@media (max-aspect-ratio: 4/5) {\n${port.join('\n')}\n}\n`;
}

const paragraphs = (arr) => (Array.isArray(arr) ? arr : [arr]).map((p) => `<p>${esc(p)}</p>`).join('\n');

// ---------- Layout ----------

function layout({ lang, page, alternates, title, description, body, noindex = false, jsonLd = '', intro = false }) {
  const tx = t[lang];
  const other = lang === 'de' ? 'en' : 'de';
  const url = site.domain + alternates[lang];
  const isHome = page === 'home';
  const home = routes.home[lang];
  const a = tx.anchors;
  const navHref = (anchor) => (isHome ? `#${anchor}` : `${home}#${anchor}`);
  const showUseCases = publishedUseCases.length > 0;

  const hreflang = LANGS.map(
    (l) => `<link rel="alternate" hreflang="${l}" href="${site.domain}${alternates[l]}">`
  ).join('\n  ');

  return `<!doctype html>
<html lang="${lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${esc(title)}</title>
  <meta name="description" content="${esc(description)}">
  ${noindex ? '<meta name="robots" content="noindex, nofollow">' : ''}
  <link rel="canonical" href="${url}">
  ${hreflang}
  <link rel="alternate" hreflang="x-default" href="${site.domain}${alternates.de}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="4ELEMENTS">
  <meta property="og:locale" content="${tx.locale}">
  <meta property="og:locale:alternate" content="${t[other].locale}">
  <meta property="og:url" content="${url}">
  <meta property="og:title" content="${esc(title)}">
  <meta property="og:description" content="${esc(description)}">
  <meta property="og:image" content="${site.domain}/assets/img/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#ffffff">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preload" href="/assets/fonts/inter-latin-400-normal.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/inter-latin-600-normal.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="${cssUrl}">${intro ? `\n  <link rel="stylesheet" href="${introStyles().url}">\n  <script src="${introJsUrl}"></script>` : ''}
  <noscript><link rel="stylesheet" href="/assets/css/nojs.css"></noscript>
  <script src="${jsUrl}" defer></script>${jsonLd}
</head>
<body>${intro ? '\n  ' + introBlock(lang) : ''}
  <a class="skip-link" href="#main">${esc(tx.ui.skipLink)}</a>
  <header class="site-header">
    <div class="container site-header__inner">
      <a class="logo" href="${home}">
        <span class="logo__name">4ELEMENTS</span>
        <span class="logo__tagline">${esc(tx.ui.logoTagline)}</span>
      </a>
      <button class="menu-toggle" type="button" aria-expanded="false" aria-controls="site-nav"
        data-label-open="${esc(tx.ui.menuOpen)}" data-label-close="${esc(tx.ui.menuClose)}">
        <span class="visually-hidden">${esc(tx.ui.menuOpen)}</span>
        <span class="menu-toggle__bars" aria-hidden="true"></span>
      </button>
      <nav class="site-nav" id="site-nav" aria-label="${esc(tx.ui.navLabel)}">
        <ul class="site-nav__list">
          <li><a href="${navHref(a.services)}">${esc(tx.nav.services)}</a></li>
          <li><a href="${navHref(a.support)}">${esc(tx.nav.support)}</a></li>
          <li><a href="${navHref(a.process)}">${esc(tx.nav.process)}</a></li>
          ${showUseCases ? `<li><a href="${routes.useCases[lang]}"${page === 'useCases' ? ' aria-current="page"' : ''}>${esc(tx.nav.useCases)}</a></li>` : ''}
          <li><a href="${navHref(a.contact)}">${esc(tx.nav.contact)}</a></li>
        </ul>
        <ul class="lang-switch" aria-label="${esc(tx.ui.langSwitchLabel)}">
          ${LANGS.map((l) =>
            l === lang
              ? `<li><a href="${alternates[l]}" hreflang="${l}" lang="${l}" aria-current="true">${l.toUpperCase()}</a></li>`
              : `<li><a href="${alternates[l]}" hreflang="${l}" lang="${l}">${l.toUpperCase()}</a></li>`
          ).join('<li aria-hidden="true" class="lang-switch__sep">|</li>')}
        </ul>
      </nav>
    </div>
  </header>

  <main id="main" tabindex="-1">
${body}
  </main>

  <footer class="site-footer">
    <div class="container site-footer__inner">
      <ul class="site-footer__links">
        <li><a href="${routes.imprint[lang]}"${page === 'imprint' ? ' aria-current="page"' : ''}>${esc(tx.footer.imprint)}</a></li>
        <li><a href="${routes.privacy[lang]}"${page === 'privacy' ? ' aria-current="page"' : ''}>${esc(tx.footer.privacy)}</a></li>
        <li>${esc(tx.footer.copyright)}</li>
      </ul>
    </div>
  </footer>
</body>
</html>
`;
}

// ---------- Seiten ----------

function homePage(lang) {
  const tx = t[lang];
  const a = tx.anchors;
  const photo = site.portrait
    ? image(site.portrait, tx.about.photoAlt, 'about__photo')
    : `<div class="about__photo about__photo--placeholder" role="img" aria-label="${esc(tx.about.photoAlt)}"><span>${esc(tx.about.photoPlaceholder)}</span></div>`;

  const body = `
    <section class="hero">
      <div class="container hero__inner">
        <div class="hero__text">
          <h1 class="hero__title">${esc(tx.hero.headline)}</h1>
          <p class="hero__subline">${esc(tx.hero.subline)}</p>
          <a class="button" href="#${a.contact}">${esc(tx.hero.button)}</a>
        </div>
        <div class="hero__visual">
          ${heroScene(tx.hero.modules, tx.ui.flowLabel)}
        </div>
      </div>
    </section>

    <section class="section problem" aria-labelledby="problem-title">
      <div class="container container--narrow" data-reveal>
        <h2 class="eyebrow" id="problem-title">${esc(tx.problem.label)}</h2>
        <p class="problem__text">${esc(tx.problem.text)}</p>
      </div>
    </section>

    <section class="section section--alt" id="${a.services}" aria-labelledby="services-title">
      <div class="container">
        <h2 class="section__title" id="services-title">${esc(tx.services.headline)}</h2>
        <ul class="cards">
${tx.services.cards
  .map(
    (c, i) => `          <li class="card" data-reveal>
            <span class="card__index" aria-hidden="true">${String(i + 1).padStart(2, '0')}</span>
            <h3 class="card__title">${esc(c.title)}</h3>
            <p>${esc(c.text)}</p>
          </li>`
  )
  .join('\n')}
        </ul>
      </div>
    </section>

    <section class="section section--dark" id="${a.support}" aria-labelledby="support-title">
      <div class="container">
        <h2 class="section__title" id="support-title">${esc(tx.support.headline)}</h2>
        <p class="section__lead">${esc(tx.support.subline)}</p>
        <ul class="plans">
${tx.support.plans
  .map(
    (p) => `          <li class="plan${p.highlight ? ' plan--highlight' : ''}" data-reveal>
            <h3 class="plan__name">${esc(p.name)}</h3>
            <p class="plan__price"><span class="plan__amount">${esc(p.price)}</span> <span class="plan__period">${esc(p.period)}</span></p>
            <dl class="plan__features">
              <div><dt>${esc(tx.support.labels.scenarios)}</dt><dd>${esc(p.scenarios)}</dd></div>
              <div><dt>${esc(tx.support.labels.fixes)}</dt><dd>${esc(p.fixes)}</dd></div>
              <div><dt>${esc(tx.support.labels.changes)}</dt><dd>${esc(p.changes)}</dd></div>
              <div><dt>${esc(tx.support.labels.report)}</dt><dd>${esc(p.report)}</dd></div>
            </dl>
            <a class="button${p.highlight ? '' : ' button--outline'}" href="${esc(mailto(`${tx.mail.packageSubject} ${p.name}`))}">${esc(tx.support.button)}<span class="visually-hidden">: ${esc(p.name)}</span></a>
          </li>`
  )
  .join('\n')}
        </ul>
        <p class="plans__note">${esc(tx.support.note)}</p>
      </div>
    </section>

    <section class="section" id="${a.process}" aria-labelledby="process-title">
      <div class="container">
        <h2 class="section__title" id="process-title">${esc(tx.process.headline)}</h2>
        <ol class="steps">
${tx.process.steps
  .map(
    (s, i) => `          <li class="step" data-reveal>
            <span class="step__number" aria-hidden="true">${String(i + 1).padStart(2, '0')}</span>
            <h3 class="step__title">${esc(s.title)}</h3>
            <p>${esc(s.text)}</p>
          </li>`
  )
  .join('\n')}
        </ol>
      </div>
    </section>

    <section class="section section--alt" id="${a.about}" aria-labelledby="about-title">
      <div class="container about" data-reveal>
        ${photo}
        <div class="about__text">
          <h2 class="section__title" id="about-title">${esc(tx.about.headline)}</h2>
          <p>${esc(tx.about.text)}</p>
        </div>
      </div>
    </section>

    <section class="section contact" id="${a.contact}" aria-labelledby="contact-title">
      <div class="container container--narrow" data-reveal>
        <h2 class="section__title" id="contact-title">${esc(tx.contact.headline)}</h2>
        <p class="contact__text">${esc(tx.contact.text)}</p>
        <a class="button button--large" href="${esc(mailto(tx.mail.subject))}">${esc(tx.contact.button)}</a>
        <p class="contact__address"><a href="${esc(mailto(tx.mail.subject))}">${esc(site.email)}</a></p>
      </div>
    </section>`;

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'ProfessionalService',
    name: site.company,
    url: site.domain + routes.home[lang],
    email: site.email,
    image: `${site.domain}/assets/img/og-image.png`,
    description: tx.meta.description,
    founder: { '@type': 'Person', name: site.owner },
    address: {
      '@type': 'PostalAddress',
      streetAddress: site.street,
      postalCode: site.postalCode,
      addressLocality: site.city,
      addressCountry: site.country,
    },
    areaServed: ['DE', 'AT', 'CH'],
    priceRange: '99 € – 499 €',
    ...(site.phone ? { telephone: site.phone } : {}),
  };

  return layout({
    lang,
    page: 'home',
    alternates: routes.home,
    title: tx.meta.title,
    description: tx.meta.description,
    body,
    intro: true,
    jsonLd: `\n  <script type="application/ld+json">${JSON.stringify(jsonLd).replace(/</g, '\\u003c')}</script>`,
  });
}

function imprintPage(lang) {
  const tx = t[lang].imprint;
  const row = (label, value) => (value ? `<p>${label ? `${esc(label)}: ` : ''}${value}</p>` : '');
  const body = `
    <article class="section legal">
      <div class="container container--narrow">
        <h1 class="page-title">${esc(tx.title)}</h1>
        <h2>${esc(tx.sectionProvider)}</h2>
        <p>${esc(site.company)}<br>${esc(tx.labelOwner)}: ${esc(site.owner)}<br>${esc(site.street)}<br>${esc(site.postalCode)} ${esc(site.city)}</p>
        <h2>${esc(tx.sectionContact)}</h2>
        ${row(tx.labelEmail, `<a href="mailto:${esc(site.email)}">${esc(site.email)}</a>`)}
        ${row(tx.labelPhone, site.phone ? `<a href="tel:${esc(site.phone.replace(/[^+\d]/g, ''))}">${esc(site.phone)}</a>` : '')}
        <h2>${esc(tx.sectionRegister)}</h2>
        <p>${esc(tx.labelCourt)}: ${esc(site.registerCourt)}<br>${esc(tx.labelRegisterNo)}: ${esc(site.registerNumber)}</p>
        ${site.vatId ? `<h2>${esc(tx.sectionVat)}</h2>\n        <p>${esc(tx.vatText)}<br>${esc(site.vatId)}</p>` : ''}
        <h2>${esc(tx.sectionResponsible)}</h2>
        <p>${esc(site.owner)}<br>${esc(site.street)}<br>${esc(site.postalCode)} ${esc(site.city)}</p>
      </div>
    </article>`;
  return layout({ lang, page: 'imprint', alternates: routes.imprint, title: tx.metaTitle, description: tx.metaDescription, body });
}

function privacyPage(lang) {
  const tx = t[lang].privacy;
  const html = readFileSync(join(CONTENT, 'rechtliches', `datenschutz.${lang}.html`), 'utf8');
  const body = `
    <article class="section legal">
      <div class="container container--narrow">
        <h1 class="page-title">${esc(tx.title)}</h1>
${html}
      </div>
    </article>`;
  return layout({ lang, page: 'privacy', alternates: routes.privacy, title: tx.metaTitle, description: tx.metaDescription, body });
}

function useCaseOverviewPage(lang) {
  const tx = t[lang].useCases;
  const list = publishedUseCases.length ? publishedUseCases : useCases;
  const body = `
    <section class="section">
      <div class="container">
        <h1 class="page-title">${esc(tx.overviewTitle)}</h1>
        <p class="section__lead">${esc(tx.overviewIntro)}</p>
        <ul class="cards cards--links">
${list
  .map(
    (uc) => `          <li class="card">
            <h2 class="card__title"><a class="card__link" href="${ucPath(uc, lang)}">${esc(uc[lang].h1)}</a></h2>
            <p>${esc(uc[lang].teaser)}</p>
            <span class="card__more" aria-hidden="true">${esc(tx.readMore)} →</span>
          </li>`
  )
  .join('\n')}
        </ul>
      </div>
    </section>`;
  return layout({
    lang,
    page: 'useCases',
    alternates: routes.useCases,
    title: tx.overviewMetaTitle,
    description: tx.overviewMetaDescription,
    body,
    noindex: publishedUseCases.length === 0,
  });
}

function useCasePage(uc, lang) {
  const tx = t[lang].useCases;
  const c = uc[lang];
  const screenshot = c.screenshot
    ? image(c.screenshot, c.screenshotAlt, 'usecase__screenshot')
    : `<div class="usecase__screenshot usecase__screenshot--placeholder" role="img" aria-label="${esc(c.screenshotAlt)}"><span>${esc(tx.screenshotPlaceholder)}</span></div>`;
  const body = `
    <article class="section usecase">
      <div class="container container--narrow">
        ${publishedUseCases.length ? `<p class="usecase__back"><a href="${routes.useCases[lang]}">← ${esc(tx.backToOverview)}</a></p>` : ''}
        <h1 class="page-title">${esc(c.h1)}</h1>

        <h2>${esc(tx.problemHeading)}</h2>
        ${paragraphs(c.problem)}

        <h2>${esc(tx.solutionHeading)}</h2>
        ${flow(c.flowSteps, tx.solutionHeading, 'responsive')}
        ${paragraphs(c.solution)}

        <h2>${esc(tx.resultHeading)}</h2>
        <ul class="checklist">
          ${c.result.map((r) => `<li>${esc(r)}</li>`).join('\n          ')}
        </ul>

        <h2>${esc(tx.screenshotHeading)}</h2>
        <figure class="usecase__figure">${screenshot}</figure>

        <div class="cta-box">
          <h2>${esc(tx.ctaHeading)}</h2>
          <p>${esc(tx.ctaText)}</p>
          <a class="button" href="${esc(mailto(`${t[lang].mail.subject}: ${c.h1}`))}">${esc(tx.ctaButton)}</a>
        </div>
      </div>
    </article>`;
  return layout({
    lang,
    page: 'useCase',
    alternates: { de: ucPath(uc, 'de'), en: ucPath(uc, 'en') },
    title: c.metaTitle,
    description: c.metaDescription,
    body,
    noindex: !uc.published,
  });
}

function notFoundPage() {
  const tx = t.de.notFound;
  const body = `
    <section class="section">
      <div class="container container--narrow">
        <h1 class="page-title">${esc(tx.title)}</h1>
        <p>${esc(tx.text)} <span lang="en">${esc(t.en.notFound.text)}</span></p>
        <p><a class="button" href="/">${esc(tx.button)}</a></p>
      </div>
    </section>`;
  return layout({ lang: 'de', page: '404', alternates: routes.home, title: `${tx.title} | 4ELEMENTS`, description: tx.text, body, noindex: true });
}

// ---------- Ausgabe ----------

rmSync(DIST, { recursive: true, force: true });
const written = [];
function out(path, html) {
  const file = path.endsWith('/') ? join(DIST, path, 'index.html') : join(DIST, path);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, html);
  written.push(path);
}

const sitemapEntries = [];
function page(alternates, render, { indexable = true } = {}) {
  for (const l of LANGS) out(alternates[l], render(l));
  if (indexable) sitemapEntries.push(alternates);
}

page(routes.home, homePage);
page(routes.imprint, imprintPage);
page(routes.privacy, privacyPage);
if (useCases.length) page(routes.useCases, useCaseOverviewPage, { indexable: publishedUseCases.length > 0 });
for (const uc of useCases) {
  page({ de: ucPath(uc, 'de'), en: ucPath(uc, 'en') }, (l) => useCasePage(uc, l), { indexable: uc.published });
}
out('/404.html', notFoundPage());

// sitemap.xml mit hreflang-Alternativen
const today = new Date().toISOString().slice(0, 10);
const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${sitemapEntries
  .flatMap((alt) =>
    LANGS.map(
      (l) => `  <url>
    <loc>${site.domain}${alt[l]}</loc>
    <lastmod>${today}</lastmod>
${LANGS.map((x) => `    <xhtml:link rel="alternate" hreflang="${x}" href="${site.domain}${alt[x]}"/>`).join('\n')}
    <xhtml:link rel="alternate" hreflang="x-default" href="${site.domain}${alt.de}"/>
  </url>`
    )
  )
  .join('\n')}
</urlset>
`;
out('/sitemap.xml', sitemap);
out('/robots.txt', `User-agent: *\nAllow: /\n\nSitemap: ${site.domain}/sitemap.xml\n`);

// Statische Dateien
cpSync(join(ROOT, 'assets'), join(DIST, 'assets'), { recursive: true });
cpSync(join(ROOT, 'static'), DIST, { recursive: true });
writeFileSync(join(DIST, 'assets/css/intro.css'), introStyles().css);

console.log(`Fertig: ${written.length} Dateien in dist/`);
for (const p of written) console.log('  ' + p);
const drafts = useCases.filter((uc) => !uc.published);
if (drafts.length) {
  console.log(`\nHinweis: ${drafts.length} Anwendungsfall-Seite(n) mit "published": false – gebaut, aber nicht verlinkt und nicht in der Sitemap:`);
  for (const uc of drafts) console.log(`  ${ucPath(uc, 'de')}  |  ${ucPath(uc, 'en')}`);
}
if (t.en._status === 'placeholder') console.log('\nHinweis: content/en.json enthält noch Platzhalter-Übersetzungen.');
