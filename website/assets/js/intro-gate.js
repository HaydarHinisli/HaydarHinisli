// 4ELEMENTS – entscheidet vor dem ersten Bild, ob das Intro läuft (synchron im <head>, daher kein Aufblitzen).
// Das Intro läuft nur beim ersten Besuch. Es läuft NICHT
//  - beim Neuladen der Seite oder über „Zurück“/„Vor“ im Browser,
//  - wenn man von einer anderen Seite dieser Website kommt (z. B. Impressum → Startseite),
//  - bei Sprunglinks (#kontakt) und bei „Bewegung reduzieren“,
//  - wenn es auf diesem Gerät in den letzten 30 Tagen schon gezeigt wurde.
// Gespeichert wird nur ein Datum im Browser (localStorage), keine Cookies, keine personenbezogenen Daten.
// Vorschau unabhängig davon: /?intro=3d, /?intro=kamera, /?intro=clean oder /?intro=verspielt
(function () {
  'use strict';
  var d = document.documentElement;
  var VARIANTS = ['3d', 'kamera', 'clean', 'verspielt'];
  var KEY = '4e-intro-seen';
  var DAYS = 30;
  var variant = d.getAttribute('data-intro') || 'kamera';
  var forced = null;
  try {
    var q = new URLSearchParams(location.search).get('intro');
    if (VARIANTS.indexOf(q) > -1) forced = q;
  } catch (e) { /* ältere Browser: kein Intro-Parameter */ }
  if (forced) variant = forced;
  if (VARIANTS.indexOf(variant) < 0) return;

  if (!forced) {
    try {
      if (location.hash || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      var nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      if (nav && (nav.type === 'reload' || nav.type === 'back_forward')) return;
      if (document.referrer && new URL(document.referrer).origin === location.origin) return;
      var seen = +localStorage.getItem(KEY) || 0;
      if (Date.now() - seen < DAYS * 864e5) return;
      localStorage.setItem(KEY, String(Date.now()));
    } catch (e) {
      return; // Speicher gesperrt (z. B. privater Modus mit Einschränkungen): lieber kein Intro als ein wiederholtes
    }
  }
  d.classList.add('is-intro', 'intro-' + variant);
})();
