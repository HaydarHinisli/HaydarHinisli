// 4ELEMENTS – Hell/Dunkel, entschieden vor dem ersten Bild (synchron im <head>, daher kein Aufblitzen).
// Reihenfolge: eigene Wahl über den Schalter in der Kopfzeile (localStorage, nur dieses Gerät, keine Cookies)
// → sonst die Einstellung des Geräts (prefers-color-scheme) → sonst der Standard aus content/site.json.
(function () {
  'use strict';
  var d = document.documentElement;
  var theme = d.getAttribute('data-theme-default') || 'futur';
  try {
    var saved = localStorage.getItem('4e-theme');
    if (saved === 'hell' || saved === 'futur') theme = saved;
    else if (d.getAttribute('data-theme-auto') === 'true' && window.matchMedia) {
      theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'hell' : 'futur';
    }
  } catch (e) { /* Speicher gesperrt: Standard verwenden */ }
  d.classList.remove('theme-hell', 'theme-futur');
  d.classList.add('theme-' + theme);
})();
