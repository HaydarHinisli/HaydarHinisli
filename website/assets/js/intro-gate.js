// 4ELEMENTS – entscheidet vor dem ersten Bild, ob das Intro läuft (synchron im <head>, daher kein Aufblitzen).
// Einmal pro Sitzung, nicht bei „Bewegung reduzieren“ und nicht bei Sprunglinks (#kontakt).
// Vorschau unabhängig davon: /?intro=clean oder /?intro=verspielt
(function () {
  'use strict';
  var d = document.documentElement;
  var variant = d.getAttribute('data-intro') || 'clean';
  var forced = null;
  try {
    var q = new URLSearchParams(location.search).get('intro');
    if (q === 'clean' || q === 'verspielt') forced = q;
  } catch (e) { /* ältere Browser: kein Intro-Parameter */ }
  if (forced) variant = forced;
  if (variant !== 'clean' && variant !== 'verspielt') return;
  try {
    if (!forced) {
      if (location.hash || window.matchMedia('(prefers-reduced-motion: reduce)').matches || sessionStorage.getItem('4e-intro')) return;
      sessionStorage.setItem('4e-intro', '1');
    }
  } catch (e) {
    return;
  }
  d.classList.add('is-intro', 'intro-' + variant);
})();
