// 4ELEMENTS – Intro der Startseite. Läuft synchron im <head>, damit vor dem ersten Bild feststeht,
// ob das Intro gezeigt wird (kein Aufblitzen). Nur einmal pro Sitzung, nie bei „Bewegung reduzieren“,
// nie bei Sprunglinks (#kontakt). Jeder Klick, jede Taste oder Scrollen überspringt es.
(function () {
  'use strict';
  var d = document.documentElement;
  var KEY = '4e-intro';
  try {
    if (location.hash || window.matchMedia('(prefers-reduced-motion: reduce)').matches || sessionStorage.getItem(KEY)) return;
    sessionStorage.setItem(KEY, '1');
  } catch (e) {
    return;
  }
  d.classList.add('is-intro');

  var events = ['keydown', 'wheel', 'touchstart', 'mousedown'];
  var finished = false;
  function done() {
    if (finished) return;
    finished = true;
    var o = document.getElementById('intro');
    var b = document.querySelector('.intro__skip');
    if (o) o.remove();
    if (b) b.remove();
    d.classList.remove('is-intro', 'is-intro-skip');
    events.forEach(function (e) { window.removeEventListener(e, skip, true); });
  }
  function skip() {
    if (finished || d.classList.contains('is-intro-skip')) return;
    d.classList.add('is-intro-skip');
    setTimeout(done, 400);
  }
  events.forEach(function (e) { window.addEventListener(e, skip, { capture: true, passive: true }); });

  document.addEventListener('DOMContentLoaded', function () {
    var o = document.getElementById('intro');
    if (!o) return done();
    o.addEventListener('animationend', function (ev) {
      if (ev.target === o && ev.animationName === 'intro-out') done();
    });
  });
  setTimeout(done, 7000); // Sicherheitsnetz
})();
