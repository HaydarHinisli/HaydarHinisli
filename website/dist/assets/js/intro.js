// 4ELEMENTS – Intro der Startseite.
// Make-Module fliegen aus allen Richtungen heran und verbinden sich zu einem Szenario. Dann „Run once“ wie in Make:
// ein Modul nach dem anderen arbeitet (Ring läuft im Uhrzeigersinn, dann „1“), die Daten wandern zum nächsten Modul,
// die Routen des Routers werden nacheinander abgearbeitet. Danach gleiten die vier Module des Kopfbereichs exakt an
// ihren Platz in der Seite, der Rest verschwindet.
// Nur transform/opacity (Grafikkarte) über die Web Animations API – dadurch flüssig auch auf Smartphones.
// Varianten: "clean" (Standard) und "verspielt" (3D-Kamera, Drehungen, Konfetti).
(function () {
  'use strict';
  var d = document.documentElement;
  if (!d.classList.contains('is-intro')) return;

  var intro = document.getElementById('intro');
  var skipBtn = document.querySelector('.intro__skip');
  var dataEl = document.getElementById('intro-data');
  var finished = false;
  var pageAnims = [];
  var EVENTS = ['keydown', 'wheel', 'touchstart', 'mousedown'];

  function end() {
    if (finished) return;
    finished = true;
    pageAnims.forEach(function (a) { a.cancel(); });
    if (intro) intro.remove();
    if (skipBtn) skipBtn.remove();
    d.classList.remove('is-intro', 'intro-clean', 'intro-verspielt');
    d.classList.add('intro-played');
    EVENTS.forEach(function (e) { window.removeEventListener(e, skip, true); });
  }

  function skip() {
    if (finished || !intro) return;
    pageAnims.forEach(function (a) { a.finish(); });
    if (skipBtn) skipBtn.style.visibility = 'hidden';
    intro.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 250, fill: 'forwards' }).onfinish = end;
  }

  if (!intro || !dataEl || !intro.animate || !window.KeyframeEffect) return end();
  EVENTS.forEach(function (e) { window.addEventListener(e, skip, { capture: true, passive: true }); });

  var playful = d.classList.contains('intro-verspielt');
  var data = JSON.parse(dataEl.textContent);
  var W = window.innerWidth;
  var H = window.innerHeight;
  var portrait = W / H < 0.8;
  var camera = intro.querySelector('.intro__camera');
  var stage = intro.querySelector('.intro__stage');
  var svg = intro.querySelector('.intro__links');
  var mods = Array.prototype.slice.call(stage.querySelectorAll('.intro__module'));
  var isRouter = mods.map(function (m) { return m.classList.contains('module--router'); });

  function play(el, frames, opts, list) {
    var a = el.animate(frames, opts);
    if (list) list.push(a);
    return a;
  }
  function rnd(i, s) { var x = Math.sin(i * 12.9898 + s * 78.233) * 43758.5453; return x - Math.floor(x); }
  function q(el, sel) { return el.querySelector(sel); }

  var addOK = false;
  try { addOK = new KeyframeEffect(null, [{ opacity: 1 }], { composite: 'add' }).composite === 'add'; } catch (e) { addOK = false; }

  var EASE = {
    out: 'cubic-bezier(0.16, 1, 0.3, 1)',
    inOut: 'cubic-bezier(0.65, 0, 0.35, 1)',
    soft: 'cubic-bezier(0.45, 0, 0.25, 1)',
    pop: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
  };

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
    var b = q(m, '.module__body').getBoundingClientRect();
    return { x: b.left - r.left + b.width / 2, y: b.top - r.top + b.height / 2, w: b.width };
  });
  mods.forEach(function (m, i) {
    m.style.left = pts[i][0] - offs[i].x + 'px';
    m.style.top = pts[i][1] - offs[i].y + 'px';
    m.style.transformOrigin = offs[i].x + 'px ' + offs[i].y + 'px';
  });

  // ---------- Kamera ----------
  var tilt3d = playful && addOK;
  var CAM = tilt3d
    ? { from: 'rotateX(60deg) rotateZ(-30deg) scale(0.82)', to: 'rotateX(0deg) rotateZ(0deg) scale(1)', counter: 'rotateZ(30deg) rotateX(-60deg)', duration: 2800, easing: 'cubic-bezier(0.5, 0, 0.15, 1)' }
    : { from: 'rotateX(10deg) scale(0.93)', to: 'rotateX(0deg) scale(1)', duration: 3200, easing: 'cubic-bezier(0.25, 0.6, 0.2, 1)' };
  play(camera, [{ transform: CAM.from }, { transform: CAM.to }], { duration: CAM.duration, easing: CAM.easing, fill: 'both' });
  if (playful) {
    intro.querySelectorAll('.intro__blob').forEach(function (b, i) {
      play(b, [{ transform: 'translate(0, 0) scale(1)' }, { transform: i ? 'translate(-8vw, 6vh) scale(1.2)' : 'translate(10vw, -5vh) scale(1.15)' }], { duration: 6000, easing: 'ease-in-out', fill: 'both' });
    });
  }

  // ---------- Anflug aus allen Richtungen, weiche Landung ----------
  var FLY = playful ? 1350 : 1050;
  var order = [0, 4, 7, 2, 5, 8, 1, 6, 3];
  var reach = Math.max(W, H) * (playful ? 0.9 : 0.75);
  var land = [];
  mods.forEach(function (m, i) {
    var dx = pts[i][0] - cx, dy = pts[i][1] - cy;
    var ang = Math.atan2(dy || rnd(i, 1) - 0.5, dx || rnd(i, 2) - 0.5) + (rnd(i, 3) - 0.5) * 0.9;
    var fx = Math.cos(ang) * reach, fy = Math.sin(ang) * reach;
    var from = playful
      ? 'translate3d(' + fx + 'px,' + fy + 'px,' + (-1500 + rnd(i, 4) * 800) + 'px) rotateX(' + (rnd(i, 5) > 0.5 ? 1 : -1) * (160 + rnd(i, 6) * 160) + 'deg) rotateY(' + (rnd(i, 7) > 0.5 ? 1 : -1) * (360 + rnd(i, 8) * 180) + 'deg) scale(0.6)'
      : 'translate3d(' + fx + 'px,' + fy + 'px,' + (-450 + rnd(i, 4) * 600) + 'px) rotateX(' + (rnd(i, 5) - 0.5) * 70 + 'deg) rotateY(' + (rnd(i, 7) - 0.5) * 90 + 'deg) scale(0.8)';
    var delay = 60 + order.indexOf(i) * 55;
    play(m, [
      { transform: from, opacity: 0 },
      { opacity: 1, offset: 0.25 },
      { transform: 'translate3d(0px,0px,0px) rotateX(0deg) rotateY(0deg) scale(1)', opacity: 1 },
    ], { duration: FLY, delay: delay, easing: EASE.out, fill: 'both' });
    land[i] = delay + FLY * 0.55;
    // kleines „Einrasten“ beim Ankommen
    play(q(m, '.module__body'), [{ transform: 'scale(1)' }, { transform: 'scale(1.06)', offset: 0.35 }, { transform: 'scale(1)' }], { duration: 480, delay: land[i] - 120, easing: 'ease-out' });
    if (tilt3d) {
      // Module drehen sich zur schräg blickenden Kamera
      play(m, [{ transform: CAM.counter }, { transform: 'rotateZ(0deg) rotateX(0deg)' }], { duration: CAM.duration, easing: CAM.easing, fill: 'both', composite: 'add' });
    }
  });
  var allLanded = Math.max.apply(null, land);

  // ---------- Verbindungen: entstehen, sobald beide Module da sind ----------
  var NS = 'http://www.w3.org/2000/svg';
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  svg.setAttribute('width', W);
  svg.setAttribute('height', H);
  var defs = document.createElementNS(NS, 'defs');
  svg.appendChild(defs);

  function maskedPath(p, cls, id) {
    var mask = document.createElementNS(NS, 'mask');
    mask.setAttribute('id', id);
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
    dots.setAttribute('class', cls);
    dots.setAttribute('mask', 'url(#' + id + ')');
    svg.appendChild(dots);
    return reveal;
  }

  var links = data.links.map(function (l, k) {
    var a = pts[l[0]], b = pts[l[1]], p;
    if (portrait) {
      var my = (a[1] + b[1]) / 2;
      p = 'M' + a[0] + ' ' + a[1] + 'C' + a[0] + ' ' + my + ' ' + b[0] + ' ' + my + ' ' + b[0] + ' ' + b[1];
    } else {
      var mx = (a[0] + b[0]) / 2;
      p = 'M' + a[0] + ' ' + a[1] + 'C' + mx + ' ' + a[1] + ' ' + mx + ' ' + b[1] + ' ' + b[0] + ' ' + b[1];
    }
    var grey = maskedPath(p, 'intro__dots', 'intro-m' + k);
    play(grey, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], {
      duration: 420, delay: Math.max(land[l[0]], land[l[1]]) + 40 + k * 20, easing: EASE.inOut, fill: 'both',
    });
    return { from: l[0], to: l[1], path: p, green: maskedPath(p, 'intro__dots intro__dots--done', 'intro-g' + k) };
  });

  // ---------- Run once ----------
  var packetsOK = window.CSS && CSS.supports && CSS.supports('offset-path', 'path("M0 0L1 1")');
  var spot = document.createElement('span');
  spot.className = 'intro__spot';
  var spotSize = circle * 3.6;
  spot.style.width = spot.style.height = spotSize + 'px';
  camera.insertBefore(spot, stage);
  var spotAt = null;
  function moveSpot(i, t) {
    var to = 'translate3d(' + (pts[i][0] - spotSize / 2) + 'px,' + (pts[i][1] - spotSize / 2) + 'px,0)';
    if (!spotAt) {
      play(spot, [{ transform: to, opacity: 0 }, { transform: to, opacity: 1 }], { duration: 300, delay: t - 200, fill: 'both' });
    } else {
      play(spot, [{ transform: spotAt, opacity: 1 }, { transform: to, opacity: 1 }], { duration: 300, delay: t - 200, easing: EASE.inOut, fill: 'forwards' });
    }
    spotAt = to;
  }

  // Ein Modul arbeitet: Ring läuft im Uhrzeigersinn um das Modul, dann „1“ und Abschluss-Welle
  function work(i, t, r) {
    var m = mods[i];
    moveSpot(i, t);
    if (isRouter[i]) {
      play(q(m, '.module__body'), [{ transform: 'scale(1)' }, { transform: 'scale(1.14)', offset: 0.4 }, { transform: 'scale(1)' }], { duration: r + 120, delay: t - 40, easing: 'ease-out' });
      return t + r;
    }
    play(q(m, '.module__body'), [
      { transform: 'scale(1)' }, { transform: 'scale(1.07)', offset: 0.22 }, { transform: 'scale(1.07)', offset: 0.78 }, { transform: 'scale(1)' },
    ], { duration: r + 200, delay: t - 80, easing: 'ease-in-out' });
    var total = r / 0.82;
    play(q(m, '.module__track'), [{ opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.82 }, { opacity: 0 }], { duration: total, delay: t, fill: 'forwards' });
    play(q(m, '.module__arc'), [
      { strokeDashoffset: 1, opacity: 0 },
      { strokeDashoffset: 1, opacity: 1, offset: 0.03, easing: EASE.soft },
      { strokeDashoffset: 0, opacity: 1, offset: 0.82 },
      { strokeDashoffset: 0, opacity: 0 },
    ], { duration: total, delay: t, fill: 'forwards' });
    var done = t + r;
    play(q(m, '.module__ring'), [{ transform: 'scale(1)', opacity: 0.8 }, { transform: 'scale(1.5)', opacity: 0 }], { duration: 600, delay: done, easing: 'ease-out', fill: 'forwards' });
    var c = q(m, '.module__count');
    if (c) play(c, [{ transform: 'scale(0)' }, { transform: 'scale(1)' }], { duration: 420, delay: done, easing: EASE.pop, fill: 'both' });
    return done;
  }

  // Daten wandern über eine Verbindung; die Verbindung wird dabei grün
  function travel(k, t, dur) {
    var L = links[k];
    moveSpot(L.to, t + dur);
    play(L.green, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: dur, delay: t, easing: EASE.soft, fill: 'both' });
    if (packetsOK) {
      var trail = playful ? 3 : 1;
      for (var j = 0; j < trail; j++) {
        var dot = document.createElement('span');
        dot.className = 'intro__packet' + (j ? ' intro__packet--trail' : '');
        dot.style.offsetPath = 'path("' + L.path + '")';
        camera.appendChild(dot);
        play(dot, [
          { offsetDistance: '0%', opacity: 0 },
          { opacity: j ? 0.55 - j * 0.15 : 1, offset: 0.12 },
          { opacity: j ? 0.55 - j * 0.15 : 1, offset: 0.88 },
          { offsetDistance: '100%', opacity: 0 },
        ], { duration: dur, delay: t + j * 30, easing: EASE.soft, fill: 'both' });
      }
    }
    return t + dur;
  }

  // Reihenfolge wie in Make: Auslöser, dann jede Verbindung in Listenreihenfolge (= Routen nacheinander)
  var t = allLanded - 50;
  var workCount = mods.filter(function (m, i) { return !isRouter[i]; }).length;
  var n = 0;
  function ringTime() { var r = 360 - (180 * n) / Math.max(1, workCount - 1); n++; return r; }
  function linkTime(k) { return 180 - (70 * k) / Math.max(1, links.length - 1); }
  var routeEnds = [];
  t = work(0, t, ringTime());
  var last = 0;
  links.forEach(function (L, k) {
    if (L.from !== last && isRouter[L.from]) {
      // nächste Route: der Router gibt die Daten erneut aus
      t = work(L.from, t + 40, 80);
    }
    t = travel(k, t + 15, linkTime(k));
    t = work(L.to, t, isRouter[L.to] ? 120 : ringTime());
    last = L.to;
    var next = links[k + 1];
    if (!next || next.from !== L.to) routeEnds.push({ i: L.to, t: t });
  });
  var runEnd = t;

  if (playful) {
    routeEnds.forEach(function (e) { confetti(pts[e.i], e.t, e.i); });
  }
  function confetti(p, at, seed) {
    var colors = ['#3ddc97', '#8052ff', '#ffb829', '#2d7ff9', '#ea4335'];
    for (var j = 0; j < 16; j++) {
      var c = document.createElement('span');
      c.className = 'intro__confetti';
      c.style.left = p[0] + 'px';
      c.style.top = p[1] + 'px';
      c.style.background = colors[j % colors.length];
      camera.appendChild(c);
      var a = (j / 16) * Math.PI * 2 + rnd(seed, j) * 0.5;
      var r = 60 + rnd(j, seed) * 80;
      play(c, [
        { transform: 'translate(0,0) rotate(0deg) scale(0.4)', opacity: 1 },
        { transform: 'translate(' + Math.cos(a) * r + 'px,' + (Math.sin(a) * r + 30) + 'px) rotate(' + (180 + j * 40) + 'deg) scale(1)', opacity: 0 },
      ], { duration: 1000, delay: at, easing: 'cubic-bezier(0.2, 0.7, 0.3, 1)', fill: 'both' });
    }
  }

  // Sanftes Schweben zwischen Landung und Übergabe (endet exakt in der Ausgangslage)
  var HAND = runEnd + 300;
  if (addOK) {
    mods.forEach(function (m, i) {
      var dur = 1300 + rnd(i, 9) * 500;
      var start = land[i] + 300;
      var iter = 2 * Math.floor((HAND - start) / (2 * dur));
      if (iter > 0) {
        play(m, [{ transform: 'translate3d(0,0,0)' }, { transform: 'translate3d(0,-4px,0)' }], { duration: dur, delay: start, iterations: iter, direction: 'alternate', easing: 'ease-in-out', composite: 'add' });
      }
    });
  }

  // ---------- Übergabe an die Seite ----------
  var heroBodies = Array.prototype.slice.call(document.querySelectorAll('.chain .module .module__body'));
  var heroMods = Array.prototype.slice.call(document.querySelectorAll('.chain .module'));
  var heroLinks = Array.prototype.slice.call(document.querySelectorAll('.chain .link'));
  var lastAnim;
  var GLIDE = 950;
  mods.forEach(function (m, i) {
    var h = m.getAttribute('data-hero');
    if (h !== null && heroBodies[+h]) {
      var r = heroBodies[+h].getBoundingClientRect();
      var k = r.width / offs[i].w;
      var tx = r.left + r.width / 2 - pts[i][0];
      var ty = r.top + r.height / 2 - pts[i][1];
      var delay = HAND + +h * 60;
      // kurz anheben, dann an den Platz im Kopfbereich gleiten
      lastAnim = play(m, [
        { transform: 'translate3d(0px,0px,0px) scale(1)' },
        { transform: 'translate3d(0px,-8px,0px) scale(1.06)', offset: 0.18, easing: playful ? 'cubic-bezier(0.34, 1.2, 0.64, 1)' : EASE.inOut },
        { transform: 'translate3d(' + tx + 'px,' + ty + 'px,0px) scale(' + k + ')' },
      ], { duration: GLIDE, delay: delay, easing: 'linear', fill: 'forwards' });
      // Übergabe: Position und Größe sind identisch – im Moment der Landung wird auf das echte Modul getauscht.
      // Hochformat: Beschriftung im Kopfbereich steht rechts, daher kurze Überblendung.
      var swap = portrait ? 240 : 1;
      var at = delay + GLIDE - (portrait ? 120 : 0);
      if (portrait) {
        m.querySelectorAll('.module__app, .module__action').forEach(function (lbl) {
          play(lbl, [{ opacity: 1 }, { opacity: 0 }], { duration: 250, delay: delay, fill: 'forwards' });
        });
      }
      play(m, [{ opacity: 1 }, { opacity: 0 }], { duration: swap, delay: at, fill: 'forwards' });
      if (heroMods[+h]) play(heroMods[+h], [{ opacity: 0 }, { opacity: 1 }], { duration: swap, delay: at, fill: 'forwards' }, pageAnims);
    } else {
      var ox = pts[i][0] - cx, oy = pts[i][1] - cy, len = Math.hypot(ox, oy) || 1;
      var dist = playful ? Math.max(W, H) * 0.8 : 36;
      play(m, [
        { transform: 'translate3d(0px,0px,0px) rotate(0deg) scale(1)', opacity: 1 },
        { transform: 'translate3d(' + (ox / len) * dist + 'px,' + ((oy / len) * dist + (playful ? 0 : 12)) + 'px,0px) rotate(' + (playful ? (i % 2 ? 200 : -200) : 0) + 'deg) scale(' + (playful ? 0.5 : 0.88) + ')', opacity: 0 },
      ], { duration: playful ? 750 : 480, delay: HAND - 120 + i * 30, easing: 'cubic-bezier(0.4, 0, 1, 1)', fill: 'forwards' });
    }
  });
  play(svg, [{ opacity: 1 }, { opacity: 0 }], { duration: 380, delay: HAND - 120, fill: 'forwards' });
  play(spot, [{ opacity: 1 }, { opacity: 0 }], { duration: 380, delay: HAND - 120, fill: 'forwards' });
  play(q(intro, '.intro__bg'), [{ opacity: 1 }, { opacity: 0 }], { duration: 750, delay: HAND + 200, easing: 'ease-in-out', fill: 'forwards' });
  if (skipBtn) play(skipBtn, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, delay: HAND, fill: 'forwards' });

  // Die Seite setzt sich zusammen (nur Bewegung, keine Unsichtbarkeit – der Inhalt ist sofort da)
  var header = document.querySelector('.site-header');
  if (header) play(header, [{ transform: 'translateY(-100%)' }, { transform: 'none' }], { duration: 700, delay: HAND + 300, easing: EASE.out, fill: 'backwards' }, pageAnims);
  document.querySelectorAll('.hero__text > *').forEach(function (el, i) {
    play(el, [{ transform: 'translateY(28px)' }, { transform: 'none' }], { duration: 850, delay: HAND + 350 + i * 80, easing: EASE.out, fill: 'backwards' }, pageAnims);
  });
  heroLinks.forEach(function (el, i) {
    play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: HAND + GLIDE + i * 60, fill: 'forwards' }, pageAnims);
  });
  document.querySelectorAll('.scene__ghosts, .scene__grid').forEach(function (el) {
    play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: HAND + 500, fill: 'forwards' }, pageAnims);
  });

  if (lastAnim) lastAnim.finished.then(function () { setTimeout(end, 250); }, function () {});
  setTimeout(end, HAND + 3000); // Sicherheitsnetz
})();
