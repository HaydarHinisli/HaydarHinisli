// 4ELEMENTS – mobiles Menü und dezente Einblendungen. Keine externen Anfragen.
(function () {
  'use strict';

  // Mobiles Menü
  var toggle = document.querySelector('.menu-toggle');
  var nav = document.getElementById('site-nav');
  if (toggle && nav) {
    var label = toggle.querySelector('.visually-hidden');
    var setOpen = function (open) {
      toggle.setAttribute('aria-expanded', String(open));
      nav.classList.toggle('is-open', open);
      label.textContent = toggle.getAttribute(open ? 'data-label-close' : 'data-label-open');
    };
    toggle.addEventListener('click', function () {
      setOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });
    nav.addEventListener('click', function (e) {
      if (e.target.closest('a')) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        toggle.focus();
      }
    });
    window.matchMedia('(min-width: 56em)').addEventListener('change', function (mq) {
      if (mq.matches) setOpen(false);
    });
  }

  var d = document.documentElement;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Kopfzeile: über dem Kopfbereich durchsichtig, beim Scrollen mattiertes Glas
  var onScrollHeader = function () { d.classList.toggle('is-scrolled', window.scrollY > 8); };
  onScrollHeader();
  window.addEventListener('scroll', onScrollHeader, { passive: true });

  // Hilfsfunktion: Text eines Elements in einzelne Wörter (<span>) zerlegen, <em>/<br> bleiben erhalten
  function splitWords(el, cls) {
    var n = 0;
    (function walk(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (c) {
        if (c.nodeType === 3) {
          var frag = document.createDocumentFragment();
          c.textContent.split(/(\s+)/).forEach(function (part) {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
            var s = document.createElement('span');
            s.className = cls;
            s.textContent = part;
            s.style.setProperty('--i', n++);
            frag.appendChild(s);
          });
          node.replaceChild(frag, c);
        } else if (c.nodeType === 1 && c.tagName !== 'BR') {
          walk(c);
        }
      });
    })(el);
    return el.querySelectorAll('.' + cls);
  }

  if (!reduce) {
    // Überschrift im Kopfbereich: Wörter steigen nacheinander auf
    var split = document.querySelector('[data-split]');
    if (split) { splitWords(split, 'sw'); d.classList.add('split-ready'); }

    // „Das Problem“: Wörter leuchten beim Scrollen nacheinander auf
    var wordsEl = document.querySelector('[data-words]');
    if (wordsEl) {
      var words = splitWords(wordsEl, 'w');
      d.classList.add('words-ready');
      var lightWords = function () {
        var r = wordsEl.getBoundingClientRect(), vh = window.innerHeight;
        var p = (vh * 0.85 - r.top) / (r.height + vh * 0.35);
        var lit = Math.round(Math.max(0, Math.min(1, p)) * words.length);
        for (var i = 0; i < words.length; i++) words[i].classList.toggle('is-lit', i < lit);
      };
      lightWords();
      window.addEventListener('scroll', lightWords, { passive: true });
    }

    // Kacheln und Preiskarten: Lichtfleck folgt der Maus
    document.querySelectorAll('.tile').forEach(function (t) {
      t.addEventListener('pointermove', function (e) {
        var r = t.getBoundingClientRect();
        t.style.setProperty('--mx', e.clientX - r.left + 'px');
        t.style.setProperty('--my', e.clientY - r.top + 'px');
      });
    });

    // Ablauf: Linie füllt sich beim Scrollen, erreichte Schritte leuchten
    var steps = document.querySelector('[data-progress]');
    if (steps) {
      var items = steps.querySelectorAll('.step');
      var fill = function () {
        var r = steps.getBoundingClientRect(), vh = window.innerHeight;
        var p = Math.max(0, Math.min(1, (vh * 0.8 - r.top) / (vh * 0.5)));
        steps.style.setProperty('--p', p.toFixed(3));
        for (var i = 0; i < items.length; i++) items[i].classList.toggle('is-active', p >= (i + 0.5) / items.length || (p > 0 && i === 0));
      };
      fill();
      window.addEventListener('scroll', fill, { passive: true });
    }
  }

  // Live-Protokoll in der Leistungs-Kachel: neue Zeilen laufen ein, solange die Kachel sichtbar ist
  var log = document.querySelector('[data-log]');
  if (log) {
    var lines = [];
    try { lines = JSON.parse(log.getAttribute('data-log')) || []; } catch (e) { lines = []; }
    var clock = new Date(); clock.setHours(9, 14, 2, 0);
    var idx = 0;
    var addRow = function () {
      if (!lines.length) return;
      var row = document.createElement('div');
      row.className = 'log__row';
      var time = document.createElement('span');
      time.textContent = clock.toTimeString().slice(0, 8);
      var ok = document.createElement('b');
      ok.textContent = '✓';
      row.appendChild(time); row.appendChild(ok); row.appendChild(document.createTextNode(lines[idx % lines.length]));
      log.appendChild(row);
      while (log.children.length > 3) log.removeChild(log.firstChild);
      idx++; clock = new Date(clock.getTime() + 1000 + Math.round(Math.random() * 2000));
    };
    addRow(); addRow(); addRow();
    if (!reduce && 'IntersectionObserver' in window) {
      var timer = null;
      new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting && !timer) timer = setInterval(addRow, 2200);
          else if (!en.isIntersecting && timer) { clearInterval(timer); timer = null; }
        });
      }).observe(log);
    }
  }

  // Einblendung beim Scrollen (Elemente in derselben Reihe leicht versetzt)
  var items2 = document.querySelectorAll('[data-reveal]');
  if (!reduce && 'IntersectionObserver' in window && items2.length) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: '0px 0px -8% 0px' }
    );
    var vh = window.innerHeight;
    items2.forEach(function (el) {
      var sib = el.parentElement ? Array.prototype.indexOf.call(el.parentElement.children, el) : 0;
      if (el.matches('li')) el.style.setProperty('--d', Math.min(sib, 4) * 0.08 + 's');
      if (el.getBoundingClientRect().top < vh) el.classList.add('is-visible');
      else observer.observe(el);
    });
    d.classList.add('reveal-ready');
  }
})();
