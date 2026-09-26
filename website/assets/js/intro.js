// 4ELEMENTS – Intro der Startseite.
// Make-Module fliegen aus allen Richtungen heran, verbinden sich zu einem Szenario, ein Durchlauf startet –
// danach gleiten die vier Module des Kopfbereichs exakt an ihren Platz in der Seite, der Rest verschwindet.
// Nur transform/opacity (Grafikkarte) über die Web Animations API – dadurch flüssig auch auf Smartphones.
// Zwei Varianten: "clean" (ruhig) und "verspielt" (3D-Kamera, Federbewegung, Konfetti).
(function () {
  'use strict';
  var d = document.documentElement;
  if (!d.classList.contains('is-intro')) return;

  var intro = document.getElementById('intro');
  var skipBtn = document.querySelector('.intro__skip');
  var dataEl = document.getElementById('intro-data');
  var finished = false;
  var anims = [];
  var pageAnims = [];

  function end() {
    if (finished) return;
    finished = true;
    pageAnims.forEach(function (a) { a.cancel(); });
    if (intro) intro.remove();
    if (skipBtn) skipBtn.remove();
    d.classList.remove('is-intro', 'intro-clean', 'intro-verspielt');
    d.classList.add('intro-played');
    ['keydown', 'wheel', 'touchstart', 'mousedown'].forEach(function (e) { window.removeEventListener(e, skip, true); });
  }

  function skip() {
    if (finished || !intro) return;
    pageAnims.forEach(function (a) { a.finish(); });
    var fade = intro.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 250, fill: 'forwards' });
    if (skipBtn) skipBtn.style.visibility = 'hidden';
    fade.onfinish = end;
  }

  if (!intro || !dataEl || !intro.animate) return end();
  ['keydown', 'wheel', 'touchstart', 'mousedown'].forEach(function (e) { window.addEventListener(e, skip, { capture: true, passive: true }); });

  var playful = d.classList.contains('intro-verspielt');
  var data = JSON.parse(dataEl.textContent);
  var W = window.innerWidth;
  var H = window.innerHeight;
  var portrait = W / H < 0.8;
  var camera = intro.querySelector('.intro__camera');
  var stage = intro.querySelector('.intro__stage');
  var svg = intro.querySelector('.intro__links');
  var mods = Array.prototype.slice.call(stage.querySelectorAll('.intro__module'));

  function play(el, frames, opts, list) {
    var a = el.animate(frames, opts);
    (list || anims).push(a);
    return a;
  }
  // Reproduzierbare „Zufallszahlen“ pro Modul
  function rnd(i, s) { var x = Math.sin(i * 12.9898 + s * 78.233) * 43758.5453; return x - Math.floor(x); }

  var springOK = window.CSS && CSS.supports && CSS.supports('transition-timing-function', 'linear(0, 1)');
  var EASE = {
    out: 'cubic-bezier(0.16, 1, 0.3, 1)',
    inOut: 'cubic-bezier(0.65, 0, 0.35, 1)',
    pop: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
    spring: springOK
      ? 'linear(0, 0.009, 0.035 2.1%, 0.141, 0.281 6.7%, 0.723 12.9%, 0.938 16.7%, 1.017, 1.077, 1.121, 1.149 24.3%, 1.159, 1.163, 1.161, 1.154 29.9%, 1.129 32.8%, 1.051 39.6%, 1.017 43.1%, 0.991, 0.977 51%, 0.974 53.8%, 0.975 57.1%, 0.997 69.8%, 1.003 76.9%, 1.004 83.8%, 1)'
      : 'cubic-bezier(0.34, 1.56, 0.64, 1)',
  };

  // Zeitplan (ms)
  var T = playful
    ? { fly: 1500, stagger: 60, draw: 1050, run: 1950, step: 170, hand: 3050 }
    : { fly: 1200, stagger: 55, draw: 1150, run: 1650, step: 170, hand: 2550 };

  // ---------- Positionen ----------
  var u = portrait ? Math.min(W / 3, H / 5.9) : Math.min(W / 5.8, H / 3.5, 200);
  var circle = (portrait ? 0.44 : 0.36) * u;
  stage.style.fontSize = circle / 4.75 + 'px';
  var cx = W / 2;
  var cy = H / 2;
  var pts = data.land.map(function (p) {
    return portrait ? [cx + p[1] * u * 1.05, cy + p[0] * u] : [cx + p[0] * u, cy + p[1] * u];
  });
  var offs = mods.map(function (m) {
    var r = m.getBoundingClientRect();
    var b = m.querySelector('.module__body').getBoundingClientRect();
    return { x: b.left - r.left + b.width / 2, y: b.top - r.top + b.height / 2, w: b.width };
  });
  mods.forEach(function (m, i) {
    m.style.left = pts[i][0] - offs[i].x + 'px';
    m.style.top = pts[i][1] - offs[i].y + 'px';
    m.style.transformOrigin = offs[i].x + 'px ' + offs[i].y + 'px';
  });

  // Tiefe im Ablauf (für die Reihenfolge von Verbindungen und Durchlauf)
  var depth = [0];
  data.links.forEach(function (l) { depth[l[1]] = depth[l[0]] + 1; });
  var maxDepth = Math.max.apply(null, depth);

  // ---------- 3D-Kamera (nur verspielt): von schräg oben auf die Szene, Module drehen sich zur Kamera ----------
  var CAM = { duration: 3000, easing: 'cubic-bezier(0.5, 0, 0.15, 1)', fill: 'both' };
  if (playful) {
    play(camera, [{ transform: 'rotateX(62deg) rotateZ(-32deg) scale(0.82)' }, { transform: 'rotateX(0deg) rotateZ(0deg) scale(1)' }], CAM);
    intro.querySelectorAll('.intro__blob').forEach(function (b, i) {
      play(b, [{ transform: 'translate(0, 0) scale(1)' }, { transform: i ? 'translate(-8vw, 6vh) scale(1.2)' : 'translate(10vw, -5vh) scale(1.15)' }], { duration: 4200, easing: 'ease-in-out', fill: 'both' });
    });
  }

  // ---------- Anflug ----------
  var order = [4, 0, 7, 2, 5, 8, 1, 6, 3];
  var reach = Math.max(W, H) * (playful ? 0.9 : 0.75);
  mods.forEach(function (m, i) {
    var dx = pts[i][0] - cx, dy = pts[i][1] - cy;
    var ang = Math.atan2(dy || rnd(i, 1) - 0.5, dx || rnd(i, 2) - 0.5) + (rnd(i, 3) - 0.5) * 0.9;
    var fx = Math.cos(ang) * reach, fy = Math.sin(ang) * reach;
    var from = playful
      ? 'translate3d(' + fx + 'px,' + fy + 'px,' + (-1600 + rnd(i, 4) * 900) + 'px) rotateX(' + (rnd(i, 5) > 0.5 ? 1 : -1) * (180 + rnd(i, 6) * 180) + 'deg) rotateY(' + (rnd(i, 7) > 0.5 ? 1 : -1) * (360 + rnd(i, 8) * 180) + 'deg) scale(0.6)'
      : 'translate3d(' + fx + 'px,' + fy + 'px,' + (-500 + rnd(i, 4) * 650) + 'px) rotateX(' + (rnd(i, 5) - 0.5) * 60 + 'deg) rotateY(' + (rnd(i, 7) - 0.5) * 80 + 'deg) scale(0.8)';
    var to = 'translate3d(0px,0px,0px) rotateX(0deg) rotateY(0deg) scale(1)';
    play(m, [{ transform: from, opacity: 0 }, { opacity: 1, offset: 0.3 }, { transform: to, opacity: 1 }], {
      duration: T.fly,
      delay: 80 + order.indexOf(i) * T.stagger,
      easing: playful ? EASE.spring : EASE.out,
      fill: 'both',
    });
    if (playful) {
      // Gegenrotation zur Kamera: Module stehen aufrecht, solange die Kamera schräg blickt
      play(m, [{ transform: 'rotateZ(32deg) rotateX(-62deg)' }, { transform: 'rotateZ(0deg) rotateX(0deg)' }], {
        duration: CAM.duration, easing: CAM.easing, fill: 'both', composite: 'add',
      });
    }
  });

  // ---------- Verbindungen (gepunktet wie im Make-Editor) ----------
  var NS = 'http://www.w3.org/2000/svg';
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  svg.setAttribute('width', W);
  svg.setAttribute('height', H);
  var defs = document.createElementNS(NS, 'defs');
  svg.appendChild(defs);
  var packetsOK = window.CSS && CSS.supports && CSS.supports('offset-path', 'path("M0 0L1 1")');
  var paths = data.links.map(function (l, k) {
    var a = pts[l[0]], b = pts[l[1]], p;
    if (portrait) {
      var my = (a[1] + b[1]) / 2;
      p = 'M' + a[0] + ' ' + a[1] + 'C' + a[0] + ' ' + my + ' ' + b[0] + ' ' + my + ' ' + b[0] + ' ' + b[1];
    } else {
      var mx = (a[0] + b[0]) / 2;
      p = 'M' + a[0] + ' ' + a[1] + 'C' + mx + ' ' + a[1] + ' ' + mx + ' ' + b[1] + ' ' + b[0] + ' ' + b[1];
    }
    var mask = document.createElementNS(NS, 'mask');
    mask.setAttribute('id', 'intro-m' + k);
    mask.setAttribute('maskUnits', 'userSpaceOnUse');
    mask.setAttribute('x', '0'); mask.setAttribute('y', '0');
    mask.setAttribute('width', W); mask.setAttribute('height', H);
    var reveal = document.createElementNS(NS, 'path');
    reveal.setAttribute('d', p);
    reveal.setAttribute('pathLength', '1');
    reveal.setAttribute('class', 'intro__reveal');
    mask.appendChild(reveal);
    defs.appendChild(mask);
    var dots = document.createElementNS(NS, 'path');
    dots.setAttribute('d', p);
    dots.setAttribute('class', 'intro__dots');
    dots.setAttribute('mask', 'url(#intro-m' + k + ')');
    svg.appendChild(dots);
    play(reveal, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], {
      duration: 450, delay: T.draw + depth[l[0]] * 90, easing: EASE.inOut, fill: 'both',
    });
    return p;
  });

  // ---------- Durchlauf: Datenpaket von Modul zu Modul, jedes Modul meldet „1“ ----------
  if (packetsOK) {
    data.links.forEach(function (l, k) {
      var trail = playful ? 3 : 1;
      for (var j = 0; j < trail; j++) {
        var dot = document.createElement('span');
        dot.className = 'intro__packet' + (j ? ' intro__packet--trail' : '');
        dot.style.offsetPath = 'path("' + paths[k] + '")';
        camera.appendChild(dot);
        play(dot, [
          { offsetDistance: '0%', opacity: 0 },
          { opacity: j ? 0.5 - j * 0.12 : 1, offset: 0.15 },
          { opacity: j ? 0.5 - j * 0.12 : 1, offset: 0.85 },
          { offsetDistance: '100%', opacity: 0 },
        ], { duration: T.step + 60, delay: T.run + depth[l[0]] * T.step + j * 28, easing: 'ease-in-out', fill: 'both' });
      }
    });
  }

  mods.forEach(function (m, i) {
    var at = T.run + depth[i] * T.step + (i === 0 ? -80 : 30);
    var ring = m.querySelector('.module__ring');
    var count = m.querySelector('.module__count');
    var body = m.querySelector('.module__body');
    play(ring, [{ transform: 'scale(1)', opacity: 0.9 }, { transform: 'scale(1.6)', opacity: 0 }], { duration: 650, delay: at, easing: 'ease-out', fill: 'both' });
    if (count) play(count, [{ transform: 'scale(0)' }, { transform: 'scale(1)' }], { duration: 380, delay: at + 60, easing: EASE.pop, fill: 'both' });
    if (playful) {
      play(body, [{ transform: 'scale(1)' }, { transform: 'scale(1.14)', offset: 0.35 }, { transform: 'scale(1)' }], { duration: 450, delay: at, easing: 'ease-out' });
      if (depth[i] === maxDepth) confetti(pts[i], at + 80, i);
    }
  });

  function confetti(p, at, seed) {
    var colors = ['#3ddc97', '#8052ff', '#ffb829', '#2d7ff9', '#ea4335'];
    for (var j = 0; j < 18; j++) {
      var c = document.createElement('span');
      c.className = 'intro__confetti';
      c.style.left = p[0] + 'px';
      c.style.top = p[1] + 'px';
      c.style.background = colors[j % colors.length];
      camera.appendChild(c);
      var a = (j / 18) * Math.PI * 2 + rnd(seed, j) * 0.5;
      var r = 70 + rnd(j, seed) * 90;
      play(c, [
        { transform: 'translate(0,0) rotate(0deg) scale(0.4)', opacity: 1 },
        { transform: 'translate(' + Math.cos(a) * r + 'px,' + (Math.sin(a) * r + 30) + 'px) rotate(' + (180 + j * 40) + 'deg) scale(1)', opacity: 0 },
      ], { duration: 1100, delay: at, easing: 'cubic-bezier(0.2, 0.7, 0.3, 1)', fill: 'both' });
    }
  }

  // ---------- Übergabe an die Seite ----------
  var heroBodies = Array.prototype.slice.call(document.querySelectorAll('.chain .module .module__body'));
  var heroMods = Array.prototype.slice.call(document.querySelectorAll('.chain .module'));
  var heroLinks = Array.prototype.slice.call(document.querySelectorAll('.chain .link'));
  var last;
  mods.forEach(function (m, i) {
    var h = m.getAttribute('data-hero');
    if (h !== null && heroBodies[+h]) {
      var r = heroBodies[+h].getBoundingClientRect();
      var k = r.width / offs[i].w;
      var tx = r.left + r.width / 2 - pts[i][0];
      var ty = r.top + r.height / 2 - pts[i][1];
      var delay = T.hand + +h * 50;
      last = play(m, [
        { transform: 'translate3d(0px,0px,0px) scale(1)' },
        { transform: 'translate3d(' + tx + 'px,' + ty + 'px,0px) scale(' + k + ')' },
      ], { duration: 900, delay: delay, easing: playful ? 'cubic-bezier(0.34, 1.25, 0.64, 1)' : EASE.inOut, fill: 'forwards' });
      // Übergabe: Position und Größe sind identisch – im Moment der Landung wird auf das echte Modul getauscht.
      // Hochformat: Beschriftung im Kopfbereich steht rechts, daher kurze Überblendung.
      var swap = portrait ? 240 : 1;
      if (portrait) {
        m.querySelectorAll('.module__app, .module__action').forEach(function (lbl) {
          play(lbl, [{ opacity: 1 }, { opacity: 0 }], { duration: 250, delay: delay, fill: 'forwards' });
        });
      }
      play(m, [{ opacity: 1 }, { opacity: 0 }], { duration: swap, delay: delay + 900 - (portrait ? 120 : 0), fill: 'forwards' });
      if (heroMods[+h]) play(heroMods[+h], [{ opacity: 0 }, { opacity: 1 }], { duration: swap, delay: delay + 900 - (portrait ? 120 : 0), fill: 'forwards' }, pageAnims);
    } else {
      var ox = pts[i][0] - cx, oy = pts[i][1] - cy, len = Math.hypot(ox, oy) || 1;
      var dist = playful ? Math.max(W, H) * 0.8 : 40;
      play(m, [
        { transform: 'translate3d(0px,0px,0px) rotate(0deg) scale(1)', opacity: 1 },
        { transform: 'translate3d(' + (ox / len) * dist + 'px,' + ((oy / len) * dist + (playful ? 0 : 10)) + 'px,0px) rotate(' + (playful ? (i % 2 ? 200 : -200) : 0) + 'deg) scale(' + (playful ? 0.5 : 0.85) + ')', opacity: 0 },
      ], { duration: playful ? 750 : 450, delay: T.hand - 150 + i * 25, easing: 'cubic-bezier(0.4, 0, 1, 1)', fill: 'forwards' });
    }
  });
  play(svg, [{ opacity: 1 }, { opacity: 0 }], { duration: 350, delay: T.hand - 150, fill: 'forwards' });
  play(intro.querySelector('.intro__bg'), [{ opacity: 1 }, { opacity: 0 }], { duration: 700, delay: T.hand + 150, easing: 'ease-in-out', fill: 'forwards' });
  if (skipBtn) play(skipBtn, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, delay: T.hand, fill: 'forwards' });

  // Die Seite setzt sich zusammen (nur Bewegung, keine Unsichtbarkeit – der Inhalt ist sofort da)
  var header = document.querySelector('.site-header');
  if (header) play(header, [{ transform: 'translateY(-100%)' }, { transform: 'none' }], { duration: 700, delay: T.hand + 250, easing: EASE.out, fill: 'backwards' }, pageAnims);
  document.querySelectorAll('.hero__text > *').forEach(function (el, i) {
    play(el, [{ transform: 'translateY(28px)' }, { transform: 'none' }], { duration: 850, delay: T.hand + 300 + i * 80, easing: EASE.out, fill: 'backwards' }, pageAnims);
  });
  heroLinks.forEach(function (el, i) {
    play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: T.hand + 900 + i * 50, fill: 'forwards' }, pageAnims);
  });
  document.querySelectorAll('.scene__ghosts, .scene__grid').forEach(function (el) {
    play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: T.hand + 500, fill: 'forwards' }, pageAnims);
  });

  if (last) last.finished.then(function () { setTimeout(end, 250); }, function () {});
  setTimeout(end, T.hand + 3000); // Sicherheitsnetz
})();
