/* The fight view (paf.fightview): plays the fight on the plan's clock, says what to press next, and follows a raid
   ahead of or behind the plan from one press on a boss moment. FV comes from the page. */
(function () {
  'use strict';
  var root = document.querySelector('.fv');
  if (!root || typeof FV === 'undefined') return;
  var M = FV.moments, $ = function (id) { return document.getElementById(id); };
  var LEAD = 5, NOW_FOR = 3, WIN = 12, LATE = 25;
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var st = { cur: 0, playing: false, speed: 1, sound: false, conf: [], said: {}, key: '', curRow: -1, ended: false,
             userScroll: 0, last: null, ssFrom: null };

  function mmss(t) { var s = Math.max(0, Math.round(t)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function secs(n) { n = Math.max(1, Math.ceil(n - 0.05)); return n + ' s'; }

  /* the clock: a confirmed boss moment moves every later moment by the boss's delay */
  function shift(i) {
    var s = 0, best = -1;
    st.conf.forEach(function (c) { if (M[c.i].t <= M[i].t && M[c.i].t >= best) { best = M[c.i].t; s = c.at - M[c.i].t; } });
    return s;
  }
  function eff(i) { return M[i].t + shift(i); }
  function confirmed(i) { return st.conf.some(function (c) { return c.i === i; }); }
  function phaseAt(t) {
    var p = FV.phases[0];
    FV.phases.forEach(function (x, k) {
      var i = M.findIndex(function (m) { return Math.abs(m.t - x[1]) < 0.6; });
      var start = k === 0 ? 0 : (i >= 0 ? eff(i) : x[1]);
      if (t >= start - 0.01) p = x;
    });
    return p ? p[0] : '';
  }
  function currentRow(t) { var c = -1; for (var i = 0; i < M.length; i++) if (eff(i) <= t + 0.01) c = i; return c; }
  function nextYou(t, after) {
    for (var i = 0; i < M.length; i++) {
      if (!M[i].you.length) continue;
      var e = eff(i);
      if (e >= t - NOW_FOR && (after == null || e > after + 0.5)) return i;
    }
    return -1;
  }
  function nextAnchor(t) {
    for (var i = 0; i < M.length; i++) if (M[i].anchor && eff(i) > t) return i;
    return -1;
  }
  /* the boss moment a press now would confirm: the closest one in its window, not already confirmed */
  function syncTarget(t) {
    var best = -1, bd = 1e9;
    for (var i = 0; i < M.length; i++) {
      if (!M[i].anchor || confirmed(i) || M[i].t < 1) continue;
      var d = t - eff(i);
      if (d < -WIN || d > LATE) continue;
      if (Math.abs(d) < bd) { bd = Math.abs(d); best = i; }
    }
    return best;
  }

  /* one line of what to press, its context */
  function ctx(i) { var a = M[i].anchor; return a ? 'on ' + a : (M[i].t < 0 ? 'before the pull' : ''); }
  function acts(i, big) {
    return M[i].you.map(function (y) {
      var ic = y.ic ? '<i class="ic" aria-hidden="true" style="background-image:url(\'https://wow.zamimg.com/images/wow/icons/medium/' + esc(y.ic) + '.jpg\')"></i>' : '<i class="ic none" aria-hidden="true"></i>';
      return '<div class="a">' + ic + '<div><b>' + esc(y.n) + '</b>' + (big && y.d ? '<small>lasts ' + Math.round(y.d) + ' s</small>' : '') + '</div></div>';
    }).join('');
  }
  function names(i) { return M[i].you.map(function (y) { return y.n; }).join(', then '); }

  function call(t) {
    var i = nextYou(t);
    if (i < 0) {
      if (t >= FV.end) return { key: 'end', cls: 'call soon', html: '<span class="lab">The kill <span class="cd">Keep going</span></span><p class="pend">Everything on the boss until it drops.</p>', say: '' };
      return { key: 'none', cls: 'call soon', html: '<span class="lab">Your rotation</span>', say: '' };
    }
    var dt = eff(i) - t, c = ctx(i);
    var state = dt <= 0.5 ? 'go' : dt <= LEAD ? 'ready' : 'soon';
    var lab = state === 'go' ? 'Now' : state === 'ready' ? secs(dt) : 'in ' + secs(dt);
    var kick = state === 'go' ? (c ? c.charAt(0).toUpperCase() + c.slice(1) : 'Press') : state === 'ready' ? 'Get ready' + (c ? ', ' + c : '') : 'Next' + (c ? ', ' + c : '');
    var win = state === 'soon' ? '' : '<span class="win"><i style="transform:scaleX(' + (state === 'go' ? 1 : Math.max(0, 1 - dt / LEAD)).toFixed(3) + ')"></i></span>';
    var say = state === 'go' ? names(i) + ' now' : state === 'ready' ? 'Get ready: ' + names(i) + (c ? ', ' + c : '') : '';
    return { key: i + ':' + state, i: i, state: state, cls: 'call ' + state, say: say,
             html: '<span class="lab">' + esc(kick) + ' <span class="cd">' + esc(lab) + '</span></span><div class="acts">' + acts(i, true) + '</div>' + win };
  }

  function then(t, cc) {
    if (cc.i == null) return '';
    var j = nextYou(t, eff(cc.i));
    return j < 0 ? '' : 'Then ' + names(j) + ' at ' + mmss(eff(j)) + (ctx(j) ? ' · ' + ctx(j) : '');
  }

  /* the screen reader hears what the voice says; one line at a time, never twice */
  function say(s, voiceToo) {
    if (!s) return;
    var sr = $('sr'), k = s.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').trim();
    if (st.said[k] && performance.now() - st.said[k] < 4000) return;
    st.said[k] = performance.now();
    sr.textContent = s;
    if (voiceToo && st.sound && window.speechSynthesis) {
      try { speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance(s); u.rate = 1.1; speechSynthesis.speak(u); } catch (e) { /* no voice */ }
    }
  }
  function beep() {
    if (!st.sound) return;
    try {
      var A = window.AudioContext || window.webkitAudioContext; st.ac = st.ac || new A();
      var o = st.ac.createOscillator(), g = st.ac.createGain(); o.frequency.value = 880; g.gain.value = 0.08;
      o.connect(g); g.connect(st.ac.destination); o.start(); o.stop(st.ac.currentTime + 0.12);
    } catch (e) { /* no sound */ }
  }

  function set(el, html) { if (el && el.__h !== html) { el.innerHTML = html; el.__h = html; } }
  function txt(el, s) { if (el && el.textContent !== s) el.textContent = s; }

  function render() {
    var t = st.cur, r = currentRow(t), cc = call(t);
    txt($('c-time'), t < 0 ? '−' + mmss(-t) : mmss(t));
    txt($('ss-clock'), $('c-time').textContent);
    var ph = phaseAt(t); txt($('c-phase'), ph); txt($('ss-phase'), ph);
    var m = r >= 0 ? M[r] : null;
    txt($('c-title'), t < 0 ? 'Before the pull' : m ? m.title : 'The pull');
    txt($('c-boss'), m && m.boss.length ? m.boss.join('; ') : 'Nothing for you to watch');
    txt($('c-you'), m && m.you.length && t - eff(r) < 8 ? m.you.map(function (y) { return y.n; }).join('; ') : 'Your rotation');
    ['c-call', 'ss-call'].forEach(function (id) { var el = $(id); if (!el) return; set(el, cc.html); el.className = cc.cls; });
    var th = then(t, cc); txt($('c-then'), th); txt($('ss-then'), th);
    var n = nextAnchor(t);
    if (n >= 0) {
      txt($('c-next'), M[n].anchor + ' '); txt($('c-in'), 'in ' + secs(eff(n) - t));
      var prev = 0; for (var k = n - 1; k >= 0; k--) if (M[k].anchor) { prev = eff(k); break; }
      $('c-meter').style.transform = 'scaleX(' + Math.min(1, Math.max(0, (t - prev) / Math.max(1, eff(n) - prev))).toFixed(3) + ')';
    } else { txt($('c-next'), ''); txt($('c-in'), ''); $('c-meter').style.transform = 'scaleX(0)'; }
    var s = st.playing ? syncTarget(t) : -1;
    ['c-sync', 'ss-sync'].forEach(function (id) {
      var b = $(id); if (!b) return; b.hidden = s < 0;
      if (s >= 0) txt(b.firstChild, M[s].anchor + ' started? Press');
    });
    if (cc.key !== st.key) {
      if (st.playing && cc.say) { say(cc.say, true); if (cc.state === 'go') beep(); }
      st.key = cc.key;
    }
    if (r !== st.curRow) {
      document.querySelectorAll('.fv .fm.on').forEach(function (x) { x.classList.remove('on'); });
      var row = r >= 0 ? document.querySelector('.fv .fm[data-i="' + r + '"]') : null;
      if (row) {
        row.classList.add('on');
        if (st.playing && performance.now() - st.userScroll > 4000) row.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
      }
      st.curRow = r;
    }
    bars(t);
    playBtn();
  }

  /* second screen: what comes in the next minute, as bars that empty */
  function bars(t) {
    var box = $('ss-bars'); if (!box || $('ss').hidden) return;
    var out = [];
    for (var i = 0; i < M.length && out.length < 5; i++) {
      var e = eff(i); if (e < t - 0.5 || e > t + 60) continue;
      if (!M[i].you.length && !M[i].anchor) continue;
      var mine = M[i].you.length > 0, label = mine ? names(i) : M[i].anchor;
      out.push('<div class="fbar' + (mine ? ' mine' : '') + '" role="listitem"><i class="fill" style="transform:scaleX(' + Math.max(0, Math.min(1, (e - t) / 60)).toFixed(3) + ')"></i><b>' + esc(label) + '</b><span>' + (e - t <= 0.5 ? 'now' : secs(e - t)) + '</span></div>');
    }
    set(box, out.join('') || '<p class="pend">Nothing in the next minute: your rotation.</p>');
  }

  function playBtn() {
    ['play', 'ss-play'].forEach(function (id) {
      var b = $(id); if (!b) return; var l = st.playing ? 'Pause' : (st.cur > 0 ? 'Resume' : 'Play');
      var s = b.querySelector('span'); txt(s || b, l);
    });
    document.body.classList.toggle('playing', st.playing);
    document.body.classList.toggle('live', st.playing || st.cur !== 0);
  }

  function tick(now) {
    if (!st.playing) return;
    if (st.last != null) st.cur += (now - st.last) / 1000 * st.speed;
    st.last = now;
    if (st.cur > FV.end + 30) { setPlay(false); say('Playback over. Play to start again.'); st.cur = 0; st.conf = []; render(); return; }
    render();
    requestAnimationFrame(tick);
  }
  function setPlay(on) {
    st.playing = on; st.last = null;
    if (on) requestAnimationFrame(tick);
    render();
  }
  function pullTimer() { st.cur = -10; st.conf = []; st.key = ''; setPlay(true); say('Pull in 10 seconds.'); }
  function wipe() { setPlay(false); st.cur = 0; st.conf = []; st.key = ''; render(); say('Back to the pull.'); }

  /* "it starts now": the boss moment closest to now, within its window */
  function sync() {
    if (!st.playing) return;
    var i = syncTarget(st.cur);
    if (i < 0) { say('Nothing to confirm right now.', true); return; }
    var d = Math.round(st.cur - M[i].t);
    st.conf.push({ i: i, at: st.cur });
    st.key = '';
    var how = Math.abs(d) <= 2 ? 'on time' : 'boss ' + Math.abs(d) + ' s ' + (d > 0 ? 'behind' : 'ahead of') + ' the plan';
    say(M[i].anchor + ' confirmed, ' + how + '.', true);
    render();
  }

  function openSS() { st.ssFrom = document.activeElement; $('ss').hidden = false; document.body.classList.add('ss-on'); $('ss').focus(); render(); }
  function closeSS() { $('ss').hidden = true; document.body.classList.remove('ss-on'); (st.ssFrom || $('ss-open')).focus(); }

  /* strips: each duration drawn along the clock, from the rows' positions */
  function layout() {
    var tl = $('tl'); if (!tl) return;
    tl.querySelectorAll('.strip').forEach(function (x) { x.remove(); });
    var rows = [].slice.call(tl.querySelectorAll('.fm')), base = tl.getBoundingClientRect().top;
    var pts = rows.map(function (r) { return [+r.dataset.t, r.getBoundingClientRect().top - base + 14]; }).sort(function (a, b) { return a[0] - b[0]; });
    if (pts.length < 2) return;
    function yAt(t) {
      if (t <= pts[0][0]) return pts[0][1];
      for (var k = 1; k < pts.length; k++) if (t <= pts[k][0]) { var a = pts[k - 1], b = pts[k]; return a[1] + (b[1] - a[1]) * (t - a[0]) / Math.max(0.1, b[0] - a[0]); }
      var l = pts[pts.length - 1]; return l[1] + (t - l[0]) * 2;
    }
    var spine = tl.querySelector('.fm .spine'); if (!spine) return;
    var sb = spine.getBoundingClientRect(), tlb = tl.getBoundingClientRect(), lanes = { boss: 0, you: 0 };
    FV.strips.forEach(function (s) {
      var y0 = yAt(s.t), y1 = yAt(s.t + s.d), el = document.createElement('div');
      var side = s.side === 'boss' ? -1 : 1, lane = lanes[s.side]++ % 3;
      el.className = 'strip s-' + s.k; el.setAttribute('aria-hidden', 'true'); el.title = s.n + ', ' + Math.round(s.d) + ' s';
      el.style.top = y0 + 'px'; el.style.height = Math.max(6, y1 - y0) + 'px';
      el.style.left = (sb.left - tlb.left + sb.width / 2 + side * (14 + lane * 9) - 3) + 'px';
      tl.appendChild(el);
    });
  }

  /* controls */
  $('play').addEventListener('click', function () { setPlay(!st.playing); });
  $('ss-play').addEventListener('click', function () { setPlay(!st.playing); });
  $('pull').addEventListener('click', pullTimer);
  $('ss-pull').addEventListener('click', pullTimer);
  $('c-sync').addEventListener('click', sync);
  $('ss-sync').addEventListener('click', sync);
  $('ss-open').addEventListener('click', openSS);
  $('ss-close').addEventListener('click', closeSS);
  $('ss-wipe').addEventListener('click', wipe);
  $('ss-sound').addEventListener('click', function () { st.sound = !st.sound; this.setAttribute('aria-pressed', st.sound); if (st.sound) say('Voice on.', true); });
  root.querySelectorAll('.seg [data-s]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.speed = +b.dataset.s; root.querySelectorAll('.seg [data-s]').forEach(function (x) { x.setAttribute('aria-pressed', x === b); });
    });
  });
  root.querySelectorAll('.fm .t').forEach(function (b) {
    b.addEventListener('click', function () { var i = +b.closest('.fm').dataset.i; st.cur = eff(i); st.key = ''; render(); });
  });
  var mrtB = $('mrt');
  if (mrtB) mrtB.addEventListener('click', function () {
    var box = $('mrt-text'), done = function () { txt(mrtB, 'Copied'); setTimeout(function () { txt(mrtB, 'Copy as MRT note'); }, 1500); };
    var fallback = function () { box.hidden = false; box.select(); try { document.execCommand('copy'); done(); } catch (e) { /* the box stays open */ } };
    if (navigator.clipboard) navigator.clipboard.writeText(box.value).then(done, fallback); else fallback();
  });
  document.addEventListener('keydown', function (ev) {
    var tag = (ev.target.tagName || '').toLowerCase();
    if (ev.key === 'Escape' && !$('ss').hidden) { ev.preventDefault(); closeSS(); return; }
    if (ev.ctrlKey && ev.shiftKey && (ev.code === 'Space' || ev.key === ' ')) { ev.preventDefault(); sync(); return; }
    if (ev.altKey && (ev.key === 'p' || ev.key === 'P')) { ev.preventDefault(); pullTimer(); return; }
    if ((ev.code === 'Space' || ev.key === ' ') && !ev.ctrlKey && !ev.altKey && !/^(input|textarea|select|button|a)$/.test(tag)) {
      if (!root.closest('.panel') || !root.closest('.panel').hidden) { ev.preventDefault(); setPlay(!st.playing); }
    }
  });
  window.addEventListener('wheel', function () { st.userScroll = performance.now(); }, { passive: true });
  window.addEventListener('keydown', function (ev) { if (/^(PageUp|PageDown|ArrowUp|ArrowDown|Home|End)$/.test(ev.key)) st.userScroll = performance.now(); });
  var lt; window.addEventListener('resize', function () { clearTimeout(lt); lt = setTimeout(layout, 150); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
  window.__fv = { st: st, render: render, layout: layout, sync: sync };
  layout(); render();
})();
