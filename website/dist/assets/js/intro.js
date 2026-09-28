// 4ELEMENTS – Intro der Startseite: 3D-Ego-Fahrt entlang der Workflow-Kette (Shopify → Google Sheets → OpenAI → Gmail).
// Die eigentliche Szene steckt in assets/js/intro3d.js (Three.js, Quelle: src/intro3d.js) und wird nur geladen,
// wenn das Intro tatsächlich läuft. Ob es läuft, entscheidet vorher assets/js/intro-gate.js.
(function () {
  'use strict';
  var d = document.documentElement;
  if (!d.classList.contains('is-intro')) return;

  var intro = document.getElementById('intro');
  var skipBtn = document.querySelector('.intro__skip');
  var dataEl = document.getElementById('intro-data');
  var finished = false;
  var EVENTS = ['keydown', 'wheel', 'touchstart', 'mousedown'];

  function end() {
    if (finished) return;
    finished = true;
    if (intro) intro.remove();
    if (skipBtn) skipBtn.remove();
    d.classList.remove('is-intro', 'intro-3d');
    document.querySelectorAll('.site-header, .hero__text > *').forEach(function (el) { el.style.transform = ''; });
    d.classList.add('intro-played');
    EVENTS.forEach(function (e) { window.removeEventListener(e, skip, true); });
  }

  // Überspringen: jede Eingabe (Taste, Scrollen, Tippen, Klick) blendet das Intro sofort aus
  function skip() {
    if (finished || !intro) return;
    if (skipBtn) skipBtn.style.visibility = 'hidden';
    if (intro.animate) intro.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 250, fill: 'forwards' }).onfinish = end;
    else end();
  }

  if (!intro || !dataEl) return end();
  EVENTS.forEach(function (e) { window.addEventListener(e, skip, { capture: true, passive: true }); });

  // Nur mit echter Grafikbeschleunigung: Ohne Grafikkarte (Software-Rendering) würde die 3D-Szene ruckeln
  // und die Seite blockieren – dann direkt zur Seite. (__introClock: nur für die Bild-für-Bild-Vorschau)
  var gpu = false;
  try {
    var tc = document.createElement('canvas');
    var gl = tc.getContext('webgl2', { failIfMajorPerformanceCaveat: true }) || tc.getContext('webgl', { failIfMajorPerformanceCaveat: true });
    var info = gl && gl.getExtension('WEBGL_debug_renderer_info');
    var name = gl ? String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)) : '';
    gpu = !!gl && !/swiftshader|llvmpipe|softpipe|software|basic render/i.test(name);
  } catch (e) { gpu = false; }
  if (!gpu && typeof window.__introClock !== 'function') return end();

  var data = JSON.parse(dataEl.textContent);
  var started = false;
  setTimeout(function () { if (!started) end(); }, 2500); // zu langsame Verbindung: lieber gleich zur Seite
  import(data.three).then(function (m) {
    if (finished) return;
    started = true;
    return m.run({
      container: intro,
      mods: data.modules,
      glyphs: data.glyphs,
      portrait: window.innerWidth / window.innerHeight < 0.8,
      heroBodies: Array.prototype.slice.call(document.querySelectorAll('.chain .module .module__body')),
      pageEls: Array.prototype.slice.call(document.querySelectorAll('.site-header, .hero__text > *')),
      onLanded: function () {
        document.querySelectorAll('.chain .module, .chain .link, .scene__ghosts, .scene__grid').forEach(function (el) { el.style.opacity = '1'; });
      },
      onDone: end,
    });
  }).catch(function () { end(); });
})();
