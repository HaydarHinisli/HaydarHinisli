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
    d.classList.remove('is-intro', 'intro-kamera', 'intro-clean', 'intro-verspielt');
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

  // Maskenbereich nur so groß wie die Verbindung selbst – spart Rechenzeit pro Bild
  function maskBox(mask, a, b, pad) {
    mask.setAttribute('x', Math.min(a[0], b[0]) - pad);
    mask.setAttribute('y', Math.min(a[1], b[1]) - pad);
    mask.setAttribute('width', Math.abs(a[0] - b[0]) + 2 * pad);
    mask.setAttribute('height', Math.abs(a[1] - b[1]) + 2 * pad);
  }

  if (d.classList.contains('intro-kamera')) { if (addOK) runEgo(); else runKamera(); return; }

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

  function maskedPath(p, cls, id, a, b) {
    var mask = document.createElementNS(NS, 'mask');
    mask.setAttribute('id', id);
    mask.setAttribute('maskUnits', 'userSpaceOnUse');
    maskBox(mask, a, b, 20);
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
    var grey = maskedPath(p, 'intro__dots', 'intro-m' + k, a, b);
    play(grey, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], {
      duration: 420, delay: Math.max(land[l[0]], land[l[1]]) + 40 + k * 20, easing: EASE.inOut, fill: 'both',
    });
    return { from: l[0], to: l[1], path: p, green: maskedPath(p, 'intro__dots intro__dots--done', 'intro-g' + k, a, b) };
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
  // =====================================================================================================
  // Variante „kamera“ (max. 4 s): Die Kamera folgt dem Datenpaket von Modul zu Modul entlang der Hauptroute.
  // Jedes Modul ist kurz im Mittelpunkt, arbeitet (Ring im Uhrzeigersinn, „1“), dann fährt die Kamera mit den
  // Daten zum nächsten. Am Ende zoomt sie heraus (alle Routen fertig) und die Module gleiten in den Kopfbereich.
  // Die Szene wird in Nahaufnahme-Größe aufgebaut und für die Übersicht verkleinert – dadurch bleibt alles scharf.
  // =====================================================================================================
  function runKamera() {
    var Z = portrait ? 1.8 : 2.1;
    var u = portrait ? Math.min(W / 3, H / 5.9) : Math.min(W / 5.8, H / 3.5, 200);
    var U = u * Z;
    var circle = (portrait ? 0.44 : 0.36) * u;
    stage.style.fontSize = (circle * Z) / 4.75 + 'px';
    camera.style.transformOrigin = '0 0';
    var LW = W * Z, LH = H * Z, O = [LW / 2, LH / 2];
    var cx = W / 2, cy = H / 2;
    var pts = data.land.map(function (p) {
      return portrait ? [O[0] + p[1] * U * 1.05, O[1] + p[0] * U] : [O[0] + p[0] * U, O[1] + p[1] * U];
    });
    var offs = mods.map(function (m) {
      var r = m.getBoundingClientRect(), b = q(m, '.module__body').getBoundingClientRect();
      return { x: b.left - r.left + b.width / 2, y: b.top - r.top + b.height / 2, w: b.width };
    });
    mods.forEach(function (m, i) {
      m.style.left = pts[i][0] - offs[i].x + 'px';
      m.style.top = pts[i][1] - offs[i].y + 'px';
      m.style.transformOrigin = offs[i].x + 'px ' + offs[i].y + 'px';
    });

    // Kamera-Einstellungen
    function focus(p, s) { s = s || 1; return 'translate(' + (cx - p[0] * s) + 'px,' + (cy - p[1] * s) + 'px) scale(' + s + ')'; }
    var overview = 'translate(' + (cx - O[0] / Z) + 'px,' + (cy - O[1] / Z) + 'px) scale(' + 1 / Z + ')';
    var camAt = focus(pts[0], 1.08);
    function camTo(to, t, dur, mid) {
      var frames = [{ transform: camAt }];
      if (mid) frames.push({ transform: mid, offset: 0.5 });
      frames.push({ transform: to });
      play(camera, frames, { duration: dur, delay: t, easing: EASE.inOut, fill: t === 0 ? 'both' : 'forwards' });
      camAt = to;
    }
    play(camera, [{ transform: focus(pts[0], 1.3) }, { transform: focus(pts[0], 1.08) }], { duration: 700, easing: EASE.out, fill: 'both' });

    // Hauptroute: vom Auslöser über den Router zum letzten Modul des Kopfbereichs
    var heroIdx = mods.map(function (m, i) { return m.getAttribute('data-hero') !== null ? i : -1; }).filter(function (i) { return i > -1; });
    var target = heroIdx[heroIdx.length - 1];
    var parent = {};
    data.links.forEach(function (l, k) { parent[l[1]] = { from: l[0], k: k }; });
    var route = [target];
    while (parent[route[0]]) route.unshift(parent[route[0]].from);
    var onRoute = function (i) { return route.indexOf(i) > -1; };

    // Verbindungen (Weltkoordinaten der Nahaufnahme)
    var NS = 'http://www.w3.org/2000/svg';
    svg.setAttribute('viewBox', '0 0 ' + LW + ' ' + LH);
    svg.setAttribute('width', LW);
    svg.setAttribute('height', LH);
    var defs = document.createElementNS(NS, 'defs');
    svg.appendChild(defs);
    function masked(p, cls, id, a, b) {
      var mask = document.createElementNS(NS, 'mask');
      mask.setAttribute('id', id);
      mask.setAttribute('maskUnits', 'userSpaceOnUse');
      maskBox(mask, a, b, 30);
      var rv = document.createElementNS(NS, 'path');
      rv.setAttribute('d', p); rv.setAttribute('pathLength', '1'); rv.setAttribute('class', 'intro__reveal');
      mask.appendChild(rv); defs.appendChild(mask);
      var dots = document.createElementNS(NS, 'path');
      dots.setAttribute('d', p); dots.setAttribute('class', cls); dots.setAttribute('mask', 'url(#' + id + ')');
      svg.appendChild(dots);
      return rv;
    }
    svg.classList.add('intro__links--zoom');
    var links = data.links.map(function (l, k) {
      var a = pts[l[0]], b = pts[l[1]], p;
      if (portrait) { var my = (a[1] + b[1]) / 2; p = 'M' + a[0] + ' ' + a[1] + 'C' + a[0] + ' ' + my + ' ' + b[0] + ' ' + my + ' ' + b[0] + ' ' + b[1]; }
      else { var mx = (a[0] + b[0]) / 2; p = 'M' + a[0] + ' ' + a[1] + 'C' + mx + ' ' + a[1] + ' ' + mx + ' ' + b[1] + ' ' + b[0] + ' ' + b[1]; }
      return { from: l[0], to: l[1], path: p, grey: masked(p, 'intro__dots', 'intro-m' + k, a, b), green: masked(p, 'intro__dots intro__dots--done', 'intro-g' + k, a, b) };
    });
    function linkTo(i) { for (var k = 0; k < links.length; k++) if (links[k].to === i) return k; return -1; }

    // Module erscheinen kurz bevor die Kamera sie erreicht (aus der Tiefe, mit leichtem Nachfedern)
    function appear(i, t) {
      play(mods[i], [
        { transform: 'translate3d(0,0,-260px) scale(0.55)', opacity: 0 },
        { transform: 'translate3d(0,0,0) scale(1)', opacity: 1 },
      ], { duration: 460, delay: t, easing: 'cubic-bezier(0.34, 1.35, 0.64, 1)', fill: 'both' });
      var k = linkTo(i);
      if (k > -1) play(links[k].grey, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 320, delay: t - 60, easing: EASE.inOut, fill: 'both' });
    }
    function ring(i, t, r) {
      var m = mods[i];
      if (isRouter[i]) {
        play(q(m, '.module__body'), [{ transform: 'scale(1)' }, { transform: 'scale(1.15)', offset: 0.4 }, { transform: 'scale(1)' }], { duration: r + 100, delay: t - 30, easing: 'ease-out' });
        return t + r;
      }
      var total = r / 0.85;
      play(q(m, '.module__body'), [{ transform: 'scale(1)' }, { transform: 'scale(1.06)', offset: 0.25 }, { transform: 'scale(1.06)', offset: 0.8 }, { transform: 'scale(1)' }], { duration: r + 160, delay: t - 60, easing: 'ease-in-out' });
      play(q(m, '.module__track'), [{ opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }], { duration: total, delay: t, fill: 'forwards' });
      play(q(m, '.module__arc'), [
        { strokeDashoffset: 1, opacity: 0 },
        { strokeDashoffset: 1, opacity: 1, offset: 0.03, easing: EASE.soft },
        { strokeDashoffset: 0, opacity: 1, offset: 0.85 },
        { strokeDashoffset: 0, opacity: 0 },
      ], { duration: total, delay: t, fill: 'forwards' });
      done(i, t + r);
      return t + r;
    }
    function done(i, t) {
      var m = mods[i];
      play(q(m, '.module__ring'), [{ transform: 'scale(1)', opacity: 0.8 }, { transform: 'scale(1.5)', opacity: 0 }], { duration: 550, delay: t, easing: 'ease-out', fill: 'forwards' });
      var c = q(m, '.module__count');
      if (c) play(c, [{ transform: 'scale(0)' }, { transform: 'scale(1)' }], { duration: 380, delay: t, easing: EASE.pop, fill: 'both' });
    }
    function packet(L, t, dur) {
      play(L.green, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: dur, delay: t, easing: EASE.soft, fill: 'both' });
      if (!(window.CSS && CSS.supports && CSS.supports('offset-path', 'path("M0 0L1 1")'))) return;
      var dot = document.createElement('span');
      dot.className = 'intro__packet intro__packet--zoom';
      dot.style.offsetPath = 'path("' + L.path + '")';
      camera.appendChild(dot);
      play(dot, [{ offsetDistance: '0%', opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.9 }, { offsetDistance: '100%', opacity: 0 }], { duration: dur, delay: t, easing: EASE.soft, fill: 'both' });
    }

    // ---------- Zeitplan (ms) ----------
    appear(route[0], 0);
    var t = ring(route[0], 380, 300);
    var RING = [260, 90, 240, 240];      // Arbeitszeit der folgenden Module auf der Route (Router kurz)
    var PAN = [320, 240, 260, 240];      // Kamerafahrt zum jeweils nächsten Modul
    for (var s = 1; s < route.length; s++) {
      var i = route[s], k = linkTo(i), pan = PAN[s - 1] || 240;
      appear(i, t - 280);
      if (isRouter[i]) {
        // Beim Router tauchen alle Zweige auf
        data.links.forEach(function (l) { if (l[0] === i && !onRoute(l[1])) appear(l[1], t - 120); });
      }
      camTo(focus(pts[i], isRouter[i] ? 0.95 : 1.08), t, pan, focus([(pts[route[s - 1]][0] + pts[i][0]) / 2, (pts[route[s - 1]][1] + pts[i][1]) / 2], 0.92));
      packet(links[k], t, pan);
      t = ring(i, t + pan, RING[s - 1] || 220);
    }
    // Übrige Module: erscheinen außerhalb des Bildes und sind beim Herauszoomen bereits fertig (Routen liefen nacheinander)
    var others = mods.map(function (m, i) { return i; }).filter(function (i) { return !onRoute(i) && !isRouter[i]; });
    others.forEach(function (i, n) {
      if (!parent[i] || onRoute(parent[i].from)) return; // Zweig-Anfänge sind schon da
      appear(i, t - 500 + n * 40);
    });
    others.forEach(function (i, n) {
      var L = links[linkTo(i)];
      play(L.green, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 260, delay: t - 150 + n * 70, easing: EASE.soft, fill: 'both' });
      done(i, t - 60 + n * 70);
    });
    var ZOOM = 520;
    camTo(overview, t + 60, ZOOM);
    var HAND = t + 60 + ZOOM - 40;

    // ---------- Übergabe an die Seite ----------
    var heroBodies = Array.prototype.slice.call(document.querySelectorAll('.chain .module .module__body'));
    var heroMods = Array.prototype.slice.call(document.querySelectorAll('.chain .module'));
    var heroLinks = Array.prototype.slice.call(document.querySelectorAll('.chain .link'));
    var GLIDE = 620, lastAnim;
    var sc = 1 / Z, T0 = [cx - O[0] / Z, cy - O[1] / Z];
    mods.forEach(function (m, i) {
      var h = m.getAttribute('data-hero');
      if (h !== null && heroBodies[+h]) {
        var r = heroBodies[+h].getBoundingClientRect();
        var sx = T0[0] + sc * pts[i][0], sy = T0[1] + sc * pts[i][1];
        var dx = (r.left + r.width / 2 - sx) * Z, dy = (r.top + r.height / 2 - sy) * Z;
        var k2 = r.width / (offs[i].w * sc);
        var delay = HAND + +h * 30;
        lastAnim = play(m, [
          { transform: 'translate3d(0px,0px,0px) scale(1)' },
          { transform: 'translate3d(' + dx + 'px,' + dy + 'px,0px) scale(' + k2 + ')' },
        ], { duration: GLIDE, delay: delay, easing: EASE.inOut, fill: 'forwards' });
        var swap = portrait ? 200 : 1, at = delay + GLIDE - (portrait ? 100 : 0);
        if (portrait) {
          m.querySelectorAll('.module__app, .module__action').forEach(function (lbl) {
            play(lbl, [{ opacity: 1 }, { opacity: 0 }], { duration: 200, delay: delay, fill: 'forwards' });
          });
        }
        play(m, [{ opacity: 1 }, { opacity: 0 }], { duration: swap, delay: at, fill: 'forwards' });
        if (heroMods[+h]) play(heroMods[+h], [{ opacity: 0 }, { opacity: 1 }], { duration: swap, delay: at, fill: 'forwards' }, pageAnims);
      } else {
        play(m, [{ transform: 'translate3d(0,0,0) scale(1)', opacity: 1 }, { transform: 'translate3d(0,20px,0) scale(0.9)', opacity: 0 }], { duration: 360, delay: HAND - 80 + i * 15, easing: 'cubic-bezier(0.4, 0, 1, 1)', fill: 'forwards' });
      }
    });
    play(svg, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, delay: HAND - 80, fill: 'forwards' });
    play(q(intro, '.intro__bg'), [{ opacity: 1 }, { opacity: 0 }], { duration: 520, delay: HAND + 80, easing: 'ease-in-out', fill: 'forwards' });
    if (skipBtn) play(skipBtn, [{ opacity: 1 }, { opacity: 0 }], { duration: 250, delay: HAND, fill: 'forwards' });
    var header = document.querySelector('.site-header');
    if (header) play(header, [{ transform: 'translateY(-100%)' }, { transform: 'none' }], { duration: 600, delay: HAND + 120, easing: EASE.out, fill: 'backwards' }, pageAnims);
    document.querySelectorAll('.hero__text > *').forEach(function (el, n) {
      play(el, [{ transform: 'translateY(24px)' }, { transform: 'none' }], { duration: 650, delay: HAND + 150 + n * 60, easing: EASE.out, fill: 'backwards' }, pageAnims);
    });
    heroLinks.forEach(function (el, n) {
      play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 250, delay: HAND + GLIDE + n * 40, fill: 'forwards' }, pageAnims);
    });
    document.querySelectorAll('.scene__ghosts, .scene__grid').forEach(function (el) {
      play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: HAND + 300, fill: 'forwards' }, pageAnims);
    });
    if (lastAnim) lastAnim.finished.then(function () { setTimeout(end, 60); }, function () {});
    setTimeout(end, 6000); // Sicherheitsnetz
  }
  // =====================================================================================================
  // Variante „kamera“ mit Ego-Perspektive (max. 4 s): Der Workflow liegt flach auf einem Boden im Raum.
  // Die Kamera fährt knapp über dem Boden hinter dem Datenpaket her und blickt entlang der Kette nach vorn:
  // Die nächsten Module stehen in der Tiefe, kommen näher, an jedem Modul hält die Fahrt kurz (Ring, „1“).
  // Am Ende steigt die Kamera auf, schwenkt in die Übersicht und die Module gleiten in den Kopfbereich.
  // Module stehen aufrecht und drehen sich immer zur Kamera (Gegenrotation, exakt synchron zur Kamera).
  // =====================================================================================================
  function runEgo() {
    var Z = portrait ? 1.8 : 2.1;
    var u = portrait ? Math.min(W / 3, H / 5.9) : Math.min(W / 5.8, H / 3.5, 200);
    var U = u * Z;
    var circle = (portrait ? 0.44 : 0.36) * u;
    stage.style.fontSize = (circle * Z) / 4.75 + 'px';
    intro.classList.add('intro--ego');
    intro.style.perspective = (portrait ? 760 : 950) + 'px';
    intro.style.perspectiveOrigin = '50% 28%';
    camera.style.transformOrigin = '0 0';
    var SW = Math.max(W, H) * Z * 1.6, O = [SW / 2, SW / 2];
    var cx = W / 2, cy = H / 2;
    // Weltkoordinaten: immer das Querformat-Layout (die Fahrt geht „nach vorn“, egal wie das Gerät gehalten wird)
    var pts = data.land.map(function (p) { return [O[0] + p[0] * U, O[1] + p[1] * U]; });
    var offs = mods.map(function (m) {
      var r = m.getBoundingClientRect(), b = q(m, '.module__body').getBoundingClientRect();
      return { x: b.left - r.left + b.width / 2, y: b.top - r.top + b.height / 2, w: b.width, h: b.height };
    });
    // Modul steht mit der Mitte seines Kreises auf dem Wegpunkt
    mods.forEach(function (m, i) {
      m.style.left = pts[i][0] - offs[i].x + 'px';
      m.style.top = pts[i][1] - offs[i].y + 'px';
      m.style.transformOrigin = offs[i].x + 'px ' + offs[i].y + 'px';
    });

    // Boden mit Punktraster (liegt in der Welt, läuft also perspektivisch mit)
    var floor = document.createElement('div');
    floor.className = 'intro__floor';
    floor.style.left = O[0] - 4 * U + 'px';
    floor.style.top = O[1] - 2.4 * U + 'px';
    floor.style.width = 8 * U + 'px';
    floor.style.height = 4.8 * U + 'px';
    floor.style.backgroundSize = U / 9 + 'px ' + U / 9 + 'px';
    camera.insertBefore(floor, camera.firstChild);

    // Hauptroute
    var heroIdx = mods.map(function (m, i) { return m.getAttribute('data-hero') !== null ? i : -1; }).filter(function (i) { return i > -1; });
    var parent = {};
    data.links.forEach(function (l, k) { parent[l[1]] = { from: l[0], k: k }; });
    var route = [heroIdx[heroIdx.length - 1]];
    while (parent[route[0]]) route.unshift(parent[route[0]].from);
    var onRoute = function (i) { return route.indexOf(i) > -1; };

    // Verbindungen auf dem Boden
    var NS = 'http://www.w3.org/2000/svg';
    var bx = O[0] - 2.6 * U, by = O[1] - 1.3 * U, bw = 5.2 * U, bh = 2.6 * U;
    svg.setAttribute('viewBox', bx + ' ' + by + ' ' + bw + ' ' + bh);
    svg.setAttribute('width', bw);
    svg.setAttribute('height', bh);
    svg.style.left = bx + 'px';
    svg.style.top = by + 'px';
    svg.classList.add('intro__links--zoom');
    var defs = document.createElementNS(NS, 'defs');
    svg.appendChild(defs);
    function masked(p, cls, id, a, b) {
      var mask = document.createElementNS(NS, 'mask');
      mask.setAttribute('id', id);
      mask.setAttribute('maskUnits', 'userSpaceOnUse');
      maskBox(mask, a, b, 30);
      var rv = document.createElementNS(NS, 'path');
      rv.setAttribute('d', p); rv.setAttribute('pathLength', '1'); rv.setAttribute('class', 'intro__reveal');
      mask.appendChild(rv); defs.appendChild(mask);
      var dots = document.createElementNS(NS, 'path');
      dots.setAttribute('d', p); dots.setAttribute('class', cls); dots.setAttribute('mask', 'url(#' + id + ')');
      svg.appendChild(dots);
      return rv;
    }
    var links = data.links.map(function (l, k) {
      var a = pts[l[0]], b = pts[l[1]], mx = (a[0] + b[0]) / 2;
      var p = 'M' + a[0] + ' ' + a[1] + 'C' + mx + ' ' + a[1] + ' ' + mx + ' ' + b[1] + ' ' + b[0] + ' ' + b[1];
      return { from: l[0], to: l[1], path: p, grey: masked(p, 'intro__dots', 'intro-m' + k, a, b), green: masked(p, 'intro__dots intro__dots--done', 'intro-g' + k, a, b) };
    });
    function linkTo(i) { for (var k = 0; k < links.length; k++) if (links[k].to === i) return k; return -1; }

    // ---------- Kamera: Schlüsselbilder ----------
    // Welt = verschieben zum Bildpunkt · neigen (rotateX) · drehen (rotateZ) · skalieren · Wegpunkt in die Mitte
    // Modul-Gegenrotation = rotateZ(-φ) · rotateX(-Neigung) → Module stehen aufrecht zur Kamera
    var phiO = portrait ? 90 : 0;
    var keys = [];
    function key(at, c) { keys.push({ at: at, c: c }); }
    function egoAt(p, back, tilt) {
      return { x: p[0] - back * U, y: p[1], ax: cx, ay: H * (portrait ? 0.7 : 0.68), tilt: tilt, phi: -90, s: 1 };
    }
    var overview = { x: O[0], y: O[1], ax: cx, ay: cy, tilt: 0, phi: phiO, s: 1 / Z };
    function worldT(c) {
      return 'translate(' + c.ax + 'px,' + c.ay + 'px) rotateX(' + c.tilt + 'deg) rotateZ(' + c.phi + 'deg) scale(' + c.s + ') translate(' + -c.x + 'px,' + -c.y + 'px)';
    }
    function counterT(c) { return 'rotateZ(' + -c.phi + 'deg) rotateX(' + -c.tilt + 'deg)'; }

    // Bausteine
    function appear(i, t) {
      play(mods[i], [
        { transform: 'scale(0.4)', opacity: 0 },
        { transform: 'scale(1)', opacity: 1 },
      ], { duration: 420, delay: t, easing: 'cubic-bezier(0.34, 1.4, 0.64, 1)', fill: 'both' });
      var k = linkTo(i);
      if (k > -1) play(links[k].grey, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 320, delay: t - 80, easing: EASE.inOut, fill: 'both' });
    }
    function done(i, t) {
      var m = mods[i];
      play(q(m, '.module__ring'), [{ transform: 'scale(1)', opacity: 0.8 }, { transform: 'scale(1.5)', opacity: 0 }], { duration: 550, delay: t, easing: 'ease-out', fill: 'forwards' });
      var c = q(m, '.module__count');
      if (c) play(c, [{ transform: 'scale(0)' }, { transform: 'scale(1)' }], { duration: 380, delay: t, easing: EASE.pop, fill: 'both' });
    }
    function ring(i, t, r) {
      var m = mods[i];
      if (isRouter[i]) {
        play(q(m, '.module__body'), [{ transform: 'scale(1)' }, { transform: 'scale(1.15)', offset: 0.4 }, { transform: 'scale(1)' }], { duration: r + 100, delay: t - 30, easing: 'ease-out' });
        return t + r;
      }
      var total = r / 0.85;
      play(q(m, '.module__track'), [{ opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }], { duration: total, delay: t, fill: 'forwards' });
      play(q(m, '.module__arc'), [
        { strokeDashoffset: 1, opacity: 0 },
        { strokeDashoffset: 1, opacity: 1, offset: 0.03, easing: EASE.soft },
        { strokeDashoffset: 0, opacity: 1, offset: 0.85 },
        { strokeDashoffset: 0, opacity: 0 },
      ], { duration: total, delay: t, fill: 'forwards' });
      done(i, t + r);
      return t + r;
    }
    function packet(L, t, dur) {
      play(L.green, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: dur, delay: t, easing: EASE.soft, fill: 'both' });
      if (!(window.CSS && CSS.supports && CSS.supports('offset-path', 'path("M0 0L1 1")'))) return;
      var dot = document.createElement('span');
      dot.className = 'intro__packet intro__packet--zoom';
      dot.style.offsetPath = 'path("' + L.path + '")';
      camera.appendChild(dot);
      play(dot, [{ offsetDistance: '0%', opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.9 }, { offsetDistance: '100%', opacity: 0 }], { duration: dur, delay: t, easing: EASE.soft, fill: 'both' });
    }

    // ---------- Zeitplan (ms) ----------
    var BACK = 0.7;                       // Kamera steht etwas hinter dem aktiven Modul
    key(0, egoAt(pts[route[0]], BACK + 1.1, 78));
    // Alle Module der Route und die Zweige stehen schon in der Tiefe bereit
    route.forEach(function (i, n) { appear(i, 60 + n * 70); });
    key(380, egoAt(pts[route[0]], BACK, 71));
    var t = ring(route[0], 330, 270);
    key(t, egoAt(pts[route[0]], BACK, 71));
    var RING = [230, 80, 210, 210];
    var PAN = [290, 220, 240, 220];
    var hidden = [];
    for (var s = 1; s < route.length; s++) {
      var i = route[s], pan = PAN[s - 1] || 260;
      if (isRouter[i]) data.links.forEach(function (l) { if (l[0] === i && !onRoute(l[1])) appear(l[1], t - 200); });
      packet(links[linkTo(i)], t, pan);
      key(t + pan, egoAt(pts[i], BACK, 71));
      // Module, die mehr als eine Station hinter der Kamera liegen, ausblenden (sie kämen sonst riesig ins Bild)
      if (s >= 2) { play(mods[route[s - 2]], [{ opacity: 1 }, { opacity: 0 }], { duration: 160, delay: t, fill: 'forwards' }); hidden.push(route[s - 2]); }
      t = ring(i, t + pan, RING[s - 1] || 220);
      key(t, egoAt(pts[i], BACK, 71));
    }
    // Übrige Module: erscheinen, ihre Routen sind beim Aufsteigen bereits fertig
    var others = mods.map(function (m, n) { return n; }).filter(function (n) { return !onRoute(n); });
    others.forEach(function (n, j) {
      if (parent[n] && !onRoute(parent[n].from)) appear(n, t - 450 + j * 40);
      var L = links[linkTo(n)];
      play(L.green, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 240, delay: t - 200 + j * 60, easing: EASE.soft, fill: 'both' });
      done(n, t - 100 + j * 60);
    });
    // Aufsteigen und in die Übersicht schwenken
    var RISE = portrait ? 640 : 560;
    key(t + 60 + RISE, overview);
    hidden.forEach(function (n) { play(mods[n], [{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: t + 150, fill: 'forwards' }); });
    var HAND = t + 60 + RISE - 30;

    // Kamera und Gegenrotation als je eine Animation mit identischen Schlüsselbildern
    var total = keys[keys.length - 1].at;
    var camFrames = [], ctrFrames = [];
    keys.forEach(function (k, n) {
      var f1 = { transform: worldT(k.c), offset: k.at / total };
      var f2 = { transform: counterT(k.c), offset: k.at / total, composite: 'add' };
      if (n < keys.length - 1) { f1.easing = EASE.inOut; f2.easing = EASE.inOut; }
      camFrames.push(f1); ctrFrames.push(f2);
    });
    play(camera, camFrames, { duration: total, fill: 'both' });
    mods.forEach(function (m) { play(m, ctrFrames, { duration: total, fill: 'both', composite: 'add' }); });

    // ---------- Übergabe an die Seite ----------
    var heroBodies = Array.prototype.slice.call(document.querySelectorAll('.chain .module .module__body'));
    var heroMods = Array.prototype.slice.call(document.querySelectorAll('.chain .module'));
    var heroLinks = Array.prototype.slice.call(document.querySelectorAll('.chain .link'));
    var GLIDE = 620, lastAnim;
    var so = 1 / Z, rad = (phiO * Math.PI) / 180, cos = Math.cos(rad), sin = Math.sin(rad);
    function toScreen(p) {
      var x = (p[0] - O[0]) * so, y = (p[1] - O[1]) * so;
      return [cx + x * cos - y * sin, cy + x * sin + y * cos];
    }
    mods.forEach(function (m, i) {
      var h = m.getAttribute('data-hero');
      if (h !== null && heroBodies[+h]) {
        var r = heroBodies[+h].getBoundingClientRect();
        var sp = toScreen(pts[i]);
        var k2 = r.width / (offs[i].w * so);
        // Verschiebung im (zur Kamera gedrehten, also bildschirmparallelen) Modulraum
        var dx = (r.left + r.width / 2 - sp[0]) / so, dy = (r.top + r.height / 2 - sp[1]) / so;
        var delay = HAND + +h * 30;
        lastAnim = play(m, [
          { transform: 'translate(0px,0px) scale(1)', composite: 'add' },
          { transform: 'translate(' + dx + 'px,' + dy + 'px) scale(' + k2 + ')', composite: 'add' },
        ], { duration: GLIDE, delay: delay, easing: EASE.inOut, fill: 'forwards', composite: 'add' });
        var swap = portrait ? 200 : 1, at = delay + GLIDE - (portrait ? 100 : 0);
        if (portrait) {
          m.querySelectorAll('.module__app, .module__action').forEach(function (lbl) {
            play(lbl, [{ opacity: 1 }, { opacity: 0 }], { duration: 200, delay: delay, fill: 'forwards' });
          });
        }
        play(m, [{ opacity: 1 }, { opacity: 0 }], { duration: swap, delay: at, fill: 'forwards' });
        if (heroMods[+h]) play(heroMods[+h], [{ opacity: 0 }, { opacity: 1 }], { duration: swap, delay: at, fill: 'forwards' }, pageAnims);
      } else {
        play(m, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, delay: HAND - 60 + i * 15, fill: 'forwards' });
      }
    });
    play(svg, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, delay: HAND - 80, fill: 'forwards' });
    play(floor, [{ opacity: 1 }, { opacity: 0 }], { duration: 400, delay: HAND - 150, fill: 'forwards' });
    play(q(intro, '.intro__bg'), [{ opacity: 1 }, { opacity: 0 }], { duration: 520, delay: HAND + 80, easing: 'ease-in-out', fill: 'forwards' });
    if (skipBtn) play(skipBtn, [{ opacity: 1 }, { opacity: 0 }], { duration: 250, delay: HAND, fill: 'forwards' });
    var header = document.querySelector('.site-header');
    if (header) play(header, [{ transform: 'translateY(-100%)' }, { transform: 'none' }], { duration: 600, delay: HAND + 120, easing: EASE.out, fill: 'backwards' }, pageAnims);
    document.querySelectorAll('.hero__text > *').forEach(function (el, n) {
      play(el, [{ transform: 'translateY(24px)' }, { transform: 'none' }], { duration: 650, delay: HAND + 150 + n * 60, easing: EASE.out, fill: 'backwards' }, pageAnims);
    });
    heroLinks.forEach(function (el, n) {
      play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 250, delay: HAND + GLIDE + n * 40, fill: 'forwards' }, pageAnims);
    });
    document.querySelectorAll('.scene__ghosts, .scene__grid').forEach(function (el) {
      play(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: HAND + 300, fill: 'forwards' }, pageAnims);
    });
    if (lastAnim) lastAnim.finished.then(function () { setTimeout(end, 60); }, function () {});
    setTimeout(end, 6000); // Sicherheitsnetz
  }
})();
