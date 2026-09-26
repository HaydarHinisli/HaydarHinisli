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

  // Einblendung beim Scrollen – nur wenn „Bewegung reduzieren“ nicht aktiv ist
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var items = document.querySelectorAll('[data-reveal]');
  if (!reduce && 'IntersectionObserver' in window && items.length) {
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
    // Bereits sichtbare Elemente nicht erst ausblenden
    var vh = window.innerHeight;
    items.forEach(function (el) {
      if (el.getBoundingClientRect().top < vh) el.classList.add('is-visible');
      else observer.observe(el);
    });
    document.documentElement.classList.add('reveal-ready');
  }
})();
