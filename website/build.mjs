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
const flowModules = readJson(join(CONTENT, 'flow-modules.json')).modules;

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
const introGateUrl = `/assets/js/intro-gate.js?v=${assetHash('assets/js/intro-gate.js')}`;
const introJsUrl = `/assets/js/intro.js?v=${assetHash('assets/js/intro.js')}`;
const introCssUrl = `/assets/css/intro.css?v=${assetHash('assets/css/intro.css')}`;
const themeUrl = `/assets/js/theme.js?v=${assetHash('assets/js/theme.js')}`;
const flowUrl = `/assets/js/flow.js?v=${assetHash('assets/js/flow.js')}`;
const intro3dUrl = `/assets/js/intro3d.js?v=${assetHash('assets/js/intro3d.js')}`;

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
  wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.3 5.3L4.5 16.5a1.8 1.8 0 0 0 2.5 2.5l4.9-4.9a4 4 0 0 0 5.3-5.3l-2.4 2.4-2.3-.6-.6-2.3 2.8-2z"/>',
  tag: '<path d="M4 12.5V5h7.5L20 13.5 13.5 20z"/><circle cx="8.5" cy="9" r="1.3"/>',
  database: '<path d="M5 6.5c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3zM5 6.5v11c0 1.7 3.1 3 7 3s7-1.3 7-3v-11M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
  card: '<rect x="3.5" y="6" width="17" height="12" rx="2"/><path d="M3.5 10h17M7 14.5h4"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  calendar: '<rect x="4" y="5.5" width="16" height="14" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  list: '<path d="M9 7h11M9 12h11M9 17h11"/><circle cx="5" cy="7" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="5" cy="17" r="1"/>',
  truck: '<path d="M3.5 7h10.5v9H3.5zM14 10h3.5l3 3v3H14"/><circle cx="7.5" cy="17.5" r="1.7"/><circle cx="17" cy="17.5" r="1.7"/>',
  image: '<rect x="4" y="4.5" width="16" height="15" rx="3"/><circle cx="12" cy="12" r="3.6"/><circle cx="16.6" cy="7.9" r=".6"/>',
  chart: '<path d="M5 19.5V11M10 19.5V6M15 19.5v-6M20 19.5V9"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 1.8"/>',
  user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
  box: '<path d="M4 7.5L12 4l8 3.5v9L12 20l-8-3.5z"/><path d="M4 7.5l8 3.5 8-3.5M12 11v9"/>',
  done: '<path d="M6 12.5l4 4 8-9"/>',
  router: '<circle cx="5.5" cy="12" r="2"/><path d="M7.5 12H11l7-6M11 12h7M11 12l7 6"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.4 3.5 5.2 3.5 8.5s-1.1 6.1-3.5 8.5c-2.4-2.4-3.5-5.2-3.5-8.5s1.1-6.1 3.5-8.5z"/>',
  braces: '<path d="M9 4.5H8a2 2 0 0 0-2 2V10a2 2 0 0 1-2 2 2 2 0 0 1 2 2v3.5a2 2 0 0 0 2 2h1M15 4.5h1a2 2 0 0 1 2 2V10a2 2 0 0 0 2 2 2 2 0 0 0-2 2v3.5a2 2 0 0 1-2 2h-1"/>',
  iterator: '<path d="M10 6.5h9.5M10 12h9.5M10 17.5h9.5"/><path d="M4 9l2.5 3L4 15"/>',
  hash: '<path d="M9.5 4l-2 16M16.5 4l-2 16M5 9h15M4 15h15"/>',
};

function moduleIcon(icon, color, cls = 'module__icon') {
  if (icon === 'logo') {
    return `<svg class="${cls}" viewBox="0 0 64 64" focusable="false"><circle cx="32" cy="32" r="32" fill="${esc(color)}"/><text x="32" y="43.5" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-size="32" font-weight="600" fill="#3ddc97">4</text></svg>`;
  }
  if (GLYPHS[icon]) {
    return `<svg class="${cls}" viewBox="0 0 64 64" focusable="false"><circle cx="32" cy="32" r="32" fill="${esc(color)}"/>${glyphSVG(icon, color)}</svg>`;
  }
  const stroke = icon === 'done' ? '#0b1f16' : '#fff';
  if (!ICONS[icon]) throw new Error(`Unbekanntes Modul-Symbol "${icon}". Erlaubt: ${Object.keys(ICONS).join(', ')}`);
  return `<svg class="${cls}" viewBox="0 0 64 64" focusable="false"><circle cx="32" cy="32" r="32" fill="${esc(color)}"/><g transform="translate(14 14) scale(1.5)" fill="none" stroke="${stroke}" stroke-width="${icon === 'done' ? 2.4 : 1.6}" stroke-linecap="round" stroke-linejoin="round">${ICONS[icon]}</g></svg>`;
}

// Flächige Symbole der Workflow-Module (64er-Raster, Kreis = Modulscheibe). Eigene Zeichnungen, keine Markenlogos.
// Dieselben Pfade zeichnet auch das 3D-Intro (src/intro3d.js). fg = weiß, bg = Modulfarbe, light = helle Modulfarbe.
const GLYPHS = {"bag":[{"d":"M20.1 26.05H43.9L45.09 47.87H18.91Z","fill":"fg"},{"d":"M26.05 26.05C26.05 16.52 37.95 16.52 37.95 26.05","stroke":"fg","w":2.38},{"d":"M27.44 29.62a1.39 1.39 0 1 1-2.78 0a1.39 1.39 0 1 1 2.78 0ZM39.34 29.62a1.39 1.39 0 1 1-2.78 0a1.39 1.39 0 1 1 2.78 0Z","fill":"bg"},{"d":"M26.44 36.96H37.56M26.44 41.52H34.38","stroke":"bg","w":1.79}],
  "sheet":[{"d":"M19.7 16.13H39.94L44.3 20.49V47.87H19.7Z","fill":"fg"},{"d":"M39.94 16.13V20.49H44.3Z","fill":"light"},{"d":"M24.86 30.41H39.14V42.32H24.86ZM24.86 36.36H39.14M24.86 39.34H39.14M30.02 30.41V42.32","stroke":"bg","w":1.49}],
  "spark":[{"d":"M30.41 21.29Q32.62 31.38 42.71 33.59Q32.62 35.8 30.41 45.89Q28.2 35.8 18.11 33.59Q28.2 31.38 30.41 21.29ZM41.92 17.32Q42.78 21.22 46.68 22.08Q42.78 22.94 41.92 26.84Q41.06 22.94 37.16 22.08Q41.06 21.22 41.92 17.32ZM42.91 39.14Q43.41 41.42 45.69 41.92Q43.41 42.42 42.91 44.7Q42.41 42.42 40.13 41.92Q42.41 41.42 42.91 39.14Z","fill":"fg"}],
  "mail":[{"d":"M18.51 20.89H45.49Q47.48 20.89 47.48 22.87V41.13Q47.48 43.11 45.49 43.11H18.51Q16.52 43.11 16.52 41.13V22.87Q16.52 20.89 18.51 20.89Z","fill":"fg"},{"d":"M18.11 22.87L32 34.38L45.89 22.87","stroke":"bg","w":2.58}]};

function mixHex(a, b, t) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return '#' + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, '0')).join('');
}
function glyphSVG(icon, color) {
  const col = { fg: '#fff', bg: color, light: mixHex(color, '#ffffff', 0.55) };
  const layer = (l, shadow) => l.fill
    ? `<path d="${l.d}" fill="${shadow ? '#000' : col[l.fill]}"/>`
    : `<path d="${l.d}" fill="none" stroke="${shadow ? '#000' : col[l.stroke]}" stroke-width="${l.w}" stroke-linecap="round" stroke-linejoin="round"/>`;
  const L = GLYPHS[icon];
  // Symbol leicht erhaben: weicher Schatten nach unten rechts (nur die weißen Flächen werfen Schatten)
  return `<g class="module__glyph-shadow" transform="translate(1.1 1.8)" opacity="0.2">${L.filter((l) => (l.fill || l.stroke) === 'fg').map((l) => layer(l, true)).join('')}</g>${L.map((l) => layer(l)).join('')}`;
}

// Ein Modul im Make-Stil (farbiger Kreis mit Symbol, Name, Aktion). Wird im Kopfbereich und im Intro verwendet.
function moduleHTML(m, cls) {
  return `<div class="module ${cls}${m.router ? ' module--router' : ''}">
              <div class="module__body">
                <svg class="module__glow" viewBox="0 0 10 10" focusable="false"><circle cx="5" cy="5" r="5" fill="${esc(m.color)}"/></svg>
                ${m.router ? '' : `<svg class="module__ports" viewBox="0 0 88 64" focusable="false"><path d="M8.2 21.8a10.2 10.2 0 0 0 0 20.4z M79.8 21.8a10.2 10.2 0 0 1 0 20.4z" fill="${esc(mixHex(m.color, '#1c1f23', 0.3))}"/></svg>`}
                <span class="module__ring"></span>
                ${moduleIcon(m.icon, m.color)}
                <span class="module__shine"></span>
                <svg class="module__progress" viewBox="0 0 100 100" focusable="false"><circle class="module__track" cx="50" cy="50" r="46"/><circle class="module__arc" cx="50" cy="50" r="46" pathLength="1"/></svg>
                ${m.trigger ? '<span class="module__trigger"><svg viewBox="0 0 24 24" focusable="false"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 8v4.5l3 1.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></span>' : ''}
                ${m.router ? '' : '<span class="module__count">1</span>'}
              </div>
              ${m.router ? '' : `<span class="module__app">${esc(m.app)}</span>
              <span class="module__action">${esc(m.action)}</span>`}
            </div>`;
}

// Verbindung zwischen zwei Modulen: kleine Kugeln, deren Farbe vom einen zum nächsten Modul übergeht (wie im Intro).
// Zwei Varianten: waagerecht (breite Spalte) und senkrecht (Smartphone), per CSS umgeschaltet.
function linkDots(from, to, n) {
  const shade = (id) => `<defs><radialGradient id="${id}" cx="36%" cy="30%" r="75%"><stop offset="0" stop-color="#fff" stop-opacity="0.6"/><stop offset="0.35" stop-color="#fff" stop-opacity="0"/><stop offset="0.75" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.32"/></radialGradient></defs>`;
  const dots = (count, pos, id) => Array.from({ length: count }, (_, k) => {
    const [x, y] = pos(k), c = mixHex(from, to, k / (count - 1));
    return `<circle cx="${x}" cy="${y}" r="4" fill="${c}"/><circle cx="${x}" cy="${y}" r="4" fill="url(#${id})"/>`;
  }).join('');
  return `<svg class="link__dots link__dots--h" viewBox="0 0 84 10" focusable="false">${shade(`ls${n}h`)}${dots(7, (k) => [6 + k * 12, 5], `ls${n}h`)}</svg>`
    + `<svg class="link__dots link__dots--v" viewBox="0 0 10 48" focusable="false">${shade(`ls${n}v`)}${dots(4, (k) => [5, 6 + k * 12], `ls${n}v`)}</svg>`;
}

const heroModules = (lang) => {
  const list = t[lang].intro.modules.filter((m) => m.hero);
  if (list.length !== 4) throw new Error(`content/${lang}.json: genau 4 Intro-Module brauchen "hero": true (aktuell ${list.length})`);
  return list;
};

// Kopfbereich: Workflow-Kette aus den vier "hero"-Modulen. Dekorativ (aria-hidden); für Screenreader gibt es die Liste darunter.
function heroScene(modules, label) {
  const chain = modules
    .map((m, i) => moduleHTML(m, `module--${i + 1}`) + (i < modules.length - 1 ? `\n            <div class="link link--${i + 1}">${linkDots(m.color, modules[i + 1].color, i + 1)}<span class="link__pulse"></span></div>` : ''))
    .join('\n            ');
  return `<div class="scene" aria-hidden="true">
          <div class="scene__grid"></div>
          <div class="chain">
            ${chain}
          </div>
        </div>
        <ol class="visually-hidden" aria-label="${esc(label)}">
          ${modules.map((m) => `<li>${esc(m.app)}: ${esc(m.action)}</li>`).join('\n          ')}
        </ol>`;
}

// ---------- Intro (nur Startseite, nur beim ersten Besuch) ----------
// Die 3D-Szene zeichnet assets/js/intro3d.js auf eine Leinwand; hier stehen nur Bühne, „Überspringen“ und die Daten
// (Texte, Farben, Symbole der Module mit "hero": true).
function introBlock(lang) {
  const tx = t[lang].intro;
  return `<div class="intro" id="intro" aria-hidden="true"></div>
  <button class="intro__skip" type="button">${esc(tx.skip)} →</button>
  <script type="application/json" id="intro-data">${JSON.stringify({ three: intro3dUrl, glyphs: GLYPHS, modules: heroModules(lang) }).replace(/</g, '\\u003c')}</script>`;
}

// Akzentwörter: *so* in den Texten wird kursiv in der Serifenschrift gesetzt
const emph = (s = '') => esc(s).replace(/\*(.+?)\*/g, '<em>$1</em>');
// Liniensymbol (24er-Raster) ohne Hintergrund, z. B. für die Leistungskacheln
const iconSVG = (name) => `<svg viewBox="0 0 24 24" focusable="false" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;

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
<html lang="${lang}" class="theme-${esc(site.theme || 'hell')}" data-theme-default="${esc(site.theme || 'hell')}" data-theme-auto="${site.themeAuto ? 'true' : 'false'}"${intro ? ` data-intro="${esc(site.introVariant || '3d')}"` : ''}>
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
  <meta name="theme-color" content="#05070a" media="(prefers-color-scheme: dark)">
  <meta name="theme-color" content="#fbfaf8" media="(prefers-color-scheme: light)">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preload" href="/assets/fonts/geist-sans-latin-400-normal.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/geist-sans-latin-500-normal.woff2" as="font" type="font/woff2" crossorigin>
  <script src="${themeUrl}"></script>
  <link rel="stylesheet" href="${cssUrl}">${intro ? `\n  <link rel="stylesheet" href="${introCssUrl}">\n  <script src="${introGateUrl}"></script>\n  <script src="${introJsUrl}" defer></script>${site.heroBackground ? `\n  <script src="${flowUrl}" defer></script>` : ''}` : ''}
  <noscript><link rel="stylesheet" href="/assets/css/nojs.css"></noscript>
  <script src="${jsUrl}" defer></script>${jsonLd}
</head>
<body>${intro ? '\n  ' + introBlock(lang) : ''}
  <div class="cursor-glow" aria-hidden="true"></div>
  <a class="skip-link" href="#main">${esc(tx.ui.skipLink)}</a>
  <header class="site-header">
    <div class="container site-header__inner">
      <a class="logo" href="${home}">
        <svg class="logo__mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false"><defs><linearGradient id="lg4" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7af5c2"/><stop offset="1" stop-color="#1fa463"/></linearGradient></defs><rect x="3" y="3" width="11" height="11" rx="3.5" fill="url(#lg4)"/><rect x="18" y="3" width="11" height="11" rx="3.5" fill="currentColor" opacity=".9"/><rect x="3" y="18" width="11" height="11" rx="3.5" fill="currentColor" opacity=".9"/><rect x="18" y="18" width="11" height="11" rx="5.5" fill="currentColor" opacity=".35"/></svg>
        <span class="logo__name"><span class="logo__four">4</span>ELEMENTS</span>
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
        <a class="button button--small nav-cta" href="${navHref(a.contact)}">${esc(tx.hero.button)} <span class="button__arrow" aria-hidden="true">→</span></a>
      </nav>
      <button class="theme-toggle" type="button" data-label-light="${esc(tx.ui.themeToLight)}" data-label-dark="${esc(tx.ui.themeToDark)}" aria-label="${esc(tx.ui.themeToLight)}" title="${esc(tx.ui.themeToLight)}">
          <svg class="theme-toggle__sun" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>
          <svg class="theme-toggle__moon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>
        </button>
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
    : '';   // ohne Foto: nur Text (kein Platzhalter)

  const kicker = (label) => `<p class="kicker">${esc(label)}</p>`;
  const tools = tx.hero.tools || [];
  const toolList = (hidden) => `<ul class="marquee__list"${hidden ? ' aria-hidden="true"' : ''}>${tools.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
  const bars = Array.from({ length: 30 }, (_, i) => `<i${i === 19 ? ' class="is-fixed"' : ''}></i>`).join('');

  const body = `
    <section class="hero">
      ${site.heroBackground ? `<div class="flow" data-flow aria-hidden="true"></div>
      <script type="application/json" id="flow-data">${JSON.stringify({ modules: flowModules, icons: ICONS, glyphs: GLYPHS }).replace(/</g, '\\u003c')}</script>` : ''}
      <div class="hero__fx" aria-hidden="true"><span class="aurora aurora--1"></span><span class="aurora aurora--2"></span><span class="hero__floor"></span></div>
      <div class="container hero__inner">
        <div class="hero__text">
          <a class="pill" href="#${a.services}"><b>${esc(tx.hero.badge)}</b> <span class="pill__text">${esc(tx.hero.badgeText)}</span> <span aria-hidden="true">→</span></a>
          <h1 class="hero__title" data-split>${emph(tx.hero.headline)}</h1>
          <p class="hero__subline">${esc(tx.hero.subline)}</p>
          <div class="hero__ctas">
            <a class="button" href="#${a.contact}">${esc(tx.hero.button)} <span class="button__arrow" aria-hidden="true">→</span></a>
            <a class="button button--ghost" href="#${a.support}">${esc(tx.hero.secondary)}</a>
          </div>
        </div>
        <div class="hero__visual window">
          <div class="window__bar" aria-hidden="true"><i></i><i></i><i></i><span>${esc(tx.hero.windowTitle)}</span><b>${esc(tx.hero.windowStatus)}</b></div>
          ${heroScene(heroModules(lang), tx.ui.flowLabel)}
        </div>
      </div>
      <div class="container marquee" data-reveal>
        <p class="marquee__label">${esc(tx.hero.toolsLabel)}</p>
        <div class="marquee__track">${toolList(false)}${toolList(true)}</div>
      </div>
    </section>

    <section class="section problem" aria-labelledby="problem-title">
      <div class="container">
        <h2 class="kicker" id="problem-title">${esc(tx.problem.label)}</h2>
        <p class="problem__text" data-words>${esc(tx.problem.text)}</p>
      </div>
    </section>

    <section class="section" id="${a.services}" aria-labelledby="services-title">
      <div class="container">
        ${kicker(tx.nav.services)}
        <h2 class="section__title" id="services-title" data-reveal>${emph(tx.services.headline)}</h2>
        <p class="section__lead" data-reveal>${esc(tx.services.lead || '')}</p>
        <ul class="bento">
          <li class="tile tile--wide" data-reveal>
            <span class="tile__icon" aria-hidden="true">${iconSVG('spark')}</span>
            <h3 class="tile__title">${esc(tx.services.cards[0].title)}</h3>
            <p>${esc(tx.services.cards[0].text)}</p>
            <div class="log" aria-hidden="true" data-log="${esc(JSON.stringify(tx.services.log || []))}"></div>
          </li>
          <li class="tile tile--stat" data-reveal>
            <h3 class="tile__title">${esc(tx.services.stat.label)}</h3>
            <p class="stat">${esc(tx.services.stat.value)}</p>
            <p>${esc(tx.services.stat.text)}</p>
          </li>
          <li class="tile" data-reveal>
            <span class="tile__icon" aria-hidden="true">${iconSVG('wrench')}</span>
            <h3 class="tile__title">${esc(tx.services.cards[1].title)}</h3>
            <p>${esc(tx.services.cards[1].text)}</p>
          </li>
          <li class="tile tile--wide" data-reveal>
            <span class="tile__icon" aria-hidden="true">${iconSVG('pulse')}</span>
            <h3 class="tile__title">${esc(tx.services.cards[2].title)}</h3>
            <p>${esc(tx.services.cards[2].text)}</p>
            <div class="uptime" aria-hidden="true">${bars}</div>
          </li>
        </ul>
      </div>
    </section>

    <section class="section section--alt" id="${a.support}" aria-labelledby="support-title">
      <div class="container">
        ${kicker(tx.nav.support)}
        <h2 class="section__title" id="support-title" data-reveal>${emph(tx.support.headline)}</h2>
        <p class="section__lead" data-reveal>${esc(tx.support.subline)}</p>
        <ul class="plans">
${tx.support.plans
  .map(
    (p) => `          <li class="plan${p.highlight ? ' plan--highlight' : ''}" data-reveal>
            <h3 class="plan__name">${esc(p.name)}${p.highlight && tx.support.badge ? ` <span class="plan__badge">${esc(tx.support.badge)}</span>` : ''}</h3>
            <p class="plan__price"><span class="plan__amount">${esc(p.price)}</span> <span class="plan__period">${esc(p.period)}</span></p>
            <dl class="plan__features">
              <div><dt>${esc(tx.support.labels.scenarios)}</dt><dd>${esc(p.scenarios)}</dd></div>
              <div><dt>${esc(tx.support.labels.fixes)}</dt><dd>${esc(p.fixes)}</dd></div>
              <div><dt>${esc(tx.support.labels.changes)}</dt><dd>${esc(p.changes)}</dd></div>
              <div><dt>${esc(tx.support.labels.report)}</dt><dd>${esc(p.report)}</dd></div>
            </dl>
            <a class="button${p.highlight ? '' : ' button--ghost'}" href="${esc(mailto(`${tx.mail.packageSubject} ${p.name}`))}">${esc(tx.support.button)}<span class="visually-hidden">: ${esc(p.name)}</span></a>
          </li>`
  )
  .join('\n')}
        </ul>
        <p class="plans__note">${esc(tx.support.note)}</p>
      </div>
    </section>

    <section class="section" id="${a.process}" aria-labelledby="process-title">
      <div class="container">
        ${kicker(tx.nav.process)}
        <h2 class="section__title" id="process-title" data-reveal>${emph(tx.process.headline)}</h2>
        <ol class="steps" data-progress>
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
      <div class="container about${site.portrait ? '' : ' about--text'}" data-reveal>
        ${photo}<div class="about__text">
          <h2 class="section__title" id="about-title">${emph(tx.about.headline)}</h2>
          <p>${esc(tx.about.text)}</p>
        </div>
      </div>
    </section>

    <section class="section contact" id="${a.contact}" aria-labelledby="contact-title">
      <div class="container">
        <div class="contact__card" data-reveal>
          ${kicker(tx.nav.contact)}
          <h2 class="section__title" id="contact-title">${emph(tx.contact.headline)}</h2>
          <p class="contact__text">${esc(tx.contact.text)}</p>
          <a class="button button--large" href="${esc(mailto(tx.mail.subject))}">${esc(tx.contact.button)} <span class="button__arrow" aria-hidden="true">→</span></a>
          <p class="contact__address"><a href="${esc(mailto(tx.mail.subject))}">${esc(site.email)}</a></p>
        </div>
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

console.log(`Fertig: ${written.length} Dateien in dist/`);
for (const p of written) console.log('  ' + p);
const drafts = useCases.filter((uc) => !uc.published);
if (drafts.length) {
  console.log(`\nHinweis: ${drafts.length} Anwendungsfall-Seite(n) mit "published": false – gebaut, aber nicht verlinkt und nicht in der Sitemap:`);
  for (const uc of drafts) console.log(`  ${ucPath(uc, 'de')}  |  ${ucPath(uc, 'en')}`);
}
if (t.en._status === 'placeholder') console.log('\nHinweis: content/en.json enthält noch Platzhalter-Übersetzungen.');
