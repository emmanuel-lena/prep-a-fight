/* The fight view (paf.fightview): plays the fight on the plan's clock, says what to press next at its own time, and
   follows a raid ahead of or behind the plan from one press on a boss event (a phase start first). FV comes from
   the page: acts (what you press), anchors (boss events a press can confirm), boss (what the boss line shows). */
(function () {
  'use strict';
  var root = document.querySelector('.fv');
  if (!root || typeof FV === 'undefined') return;
  var A = FV.acts, N = FV.anchors, B = FV.boss, $ = function (id) { return document.getElementById(id); };
  var LEAD = 5, NOW_FOR = 3, SAME = 1, BOUNCE = 3, QUIET = 1.5, LAST_PUSH = 30;
  var WIN = { pull: [-5, 10], phase: [-30, 40], immune: [-30, 40], adds: [-10, 12], cast: [-10, 12] }, FIRST = 10, NEAR = 4, CARRY = 10, FAR = 30, THEN = 60;
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var st = { cur: 0, playing: false, speed: 1, sound: false, conf: [], key: '', curRow: -1, target: -1, lastPress: -1e9,
             quietUntil: 0, userScroll: 0, last: null, ssFrom: null, sq: [], sqAt: 0, said: {} };

  function mmss(t) { var s = Math.max(0, Math.round(t)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  function clock(t) { return t < 0 ? '−' + mmss(-t) : mmss(t); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function secs(n) { return Math.max(1, Math.ceil(n - 0.05)) + ' s'; }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function visible() { var p = root.closest('.panel'); return !p || !p.hidden; }

  /* the clock: a confirmed boss event moves every later event by the boss's delay */
  function shift(pt) {
    var s = 0, best = -1e9;
    st.conf.forEach(function (c) {
      // a confirmed phase also carries what comes just before it (a defensive for its opening hit)
      var mine = c.pt <= pt + 0.01 || (c.big && c.pt > pt && c.pt - pt <= CARRY);
      if (mine && c.pt > best) { best = c.pt; s = c.at - c.pt; }
    });
    return s;
  }
  function eff(pt) { return pt + shift(pt); }
  /* an event before a confirmed phase that would only come after that phase started: the raid skipped it */
  function gone(pt) {
    return st.conf.some(function (c) { return c.big && c.pt > pt + 0.01 && eff(pt) >= c.at - 0.01; });
  }
  function lastPt() { return st.conf.reduce(function (m, c) { return Math.max(m, c.pt); }, -1e9); }
  /* a boss item lasts until the next confirmed phase starts at the latest */
  function until(b) {
    var e = eff(b.t), end = e + Math.max(b.d, 6);
    st.conf.forEach(function (c) { if (c.big && c.pt > b.t + 0.01 && c.at > e) end = Math.min(end, c.at); });
    return end;
  }
  var byEff = function () { return A.filter(function (a) { return !gone(a.t); }).sort(function (a, b) { return eff(a.t) - eff(b.t); }); };
  function confirmed(i) { return st.conf.some(function (c) { return c.i === i; }); }

  /* what you press: the next group (presses within a second of each other) still to come or just due */
  function group(t, after) {
    var L = byEff();
    for (var i = 0; i < L.length; i++) {
      var e = eff(L[i].t);
      if (e >= t - NOW_FOR && (after == null || e > after + 0.5)) {
        var g = [L[i]];
        for (var j = i + 1; j < L.length && eff(L[j].t) - e <= SAME; j++) g.push(L[j]);
        var out = { at: e, last: eff(g[g.length - 1].t), acts: g };
        if (after == null && e < t - 0.5) {  // already pressed: the next press takes over as soon as it is near
          var n = group(t, out.last);
          if (n && n.at - t <= LEAD) return n;
        }
        return out;
      }
    }
    return null;
  }
  function names(g, sep) { return g.acts.map(function (a) { return a.n; }).join(sep || ' + '); }
  function icon(ic) {
    return ic ? '<i class="ic" aria-hidden="true" style="background-image:url(\'https://wow.zamimg.com/images/wow/icons/medium/' + esc(ic) + '.jpg\')"></i>'
      : '<i class="ic none" aria-hidden="true"></i>';
  }

  function call(t) {
    var g = group(t);
    if (!g) {
      if (t >= FV.end - LAST_PUSH) {
        return { key: 'end', cls: 'call fv-next fv-end', state: 'end', say: '', html: '<span class="lab">Last push <span class="cd">' +
          (t < FV.end ? 'kill around ' + mmss(FV.end) : 'any moment') + '</span></span><p class="pend">Everything on the boss until it drops.</p>' };
      }
      return { key: 'none', cls: 'call fv-next', state: 'none', say: '', html: '<span class="lab">Your rotation</span><p class="pend">Nothing to press before the kill.</p>' };
    }
    var dt = g.at - t, c = g.acts[0].c;
    if (dt > FAR) {
      return { key: 'far' + g.at.toFixed(0), g: g, cls: 'call fv-next', state: 'far', say: '',
               html: '<span class="lab">Your rotation</span><p class="pend">Next: ' + esc(names(g)) + ' at ' + mmss(g.at) + (c ? ', ' + esc(c) : '') + '</p>' };
    }
    var state = dt <= 0.5 ? 'go' : dt <= LEAD ? 'ready' : 'soon';
    var kick = state === 'go' ? (cap(c) || 'Press') : (state === 'ready' ? 'Get ready' : 'Next') + (c ? ', ' + c : '');
    var lab = state === 'go' ? 'Now' : state === 'ready' ? secs(dt) : 'in ' + secs(dt);
    var win = state === 'soon' ? '' : '<span class="win"><i style="transform:scaleX(' + (state === 'go' ? 1 : Math.max(0, 1 - dt / LEAD)).toFixed(3) + ')"></i></span>';
    var rows = g.acts.map(function (a) {
      return '<div class="a">' + icon(a.ic) + '<div><b>' + esc(a.n) + '</b>' + (a.d && a.k !== 'move' ? '<small>lasts ' + Math.round(a.d) + ' s</small>' : '') + '</div></div>';
    }).join('');
    return { key: g.at.toFixed(1) + ':' + state, g: g, state: state, cls: 'call ' + { go: 'fv-go', ready: 'fv-soon', soon: 'fv-next' }[state],
             say: state === 'go' ? names(g, ', then ') + ', now' : state === 'ready' ? 'Get ready: ' + names(g, ', then ') + (c ? ', ' + c : '') : '',
             html: '<span class="lab">' + esc(kick) + ' <span class="cd">' + esc(lab) + '</span></span><div class="acts">' + rows + '</div>' + win };
  }
  function then(t, cc) {
    if (!cc.g) return '';
    if (cc.state === 'far') return '';
    var n = group(t, cc.g.last);
    if (!n || n.at - t > THEN) return '';
    var c = n.acts[0].c, said = names(n);
    return 'Then ' + said + ' at ' + mmss(n.at) + (c && said.indexOf(c.replace(/^on (the )?/, '')) < 0 ? ' · ' + c : '');
  }

  /* the boss line: what is running now (adds alive, the boss immune, Bloodlust) or was just cast */
  function bossNow(t) {
    var on = B.filter(function (b) { var e = eff(b.t); return !gone(b.t) && e <= t && t < until(b); });
    var moves = on.filter(function (b) { return b.k === 'move'; }).sort(function (a, b) { return until(b) - until(a); });
    on = on.filter(function (b) { return b.k !== 'move' || b === moves[0]; });  // overlapping moves: the longest
    return on.length ? on.map(function (b) {
      if (b.k === 'move') return 'Moving until ' + mmss(until(b));
      if (b.k === 'immune') return 'Boss immune, back in ' + secs(until(b) - t);
      return b.n;
    }).join('; ') : '—';
  }
  function title(t, cc) {
    if (t < 0) return 'Before the pull';
    if (cc.state === 'end') return 'Last push';
    var cur = '';
    N.forEach(function (a) {
      var e = eff(a.t), b = B.filter(function (x) { return Math.abs(x.t - a.t) < 0.01 && x.n === a.n; })[0];
      if (!gone(a.t) && e <= t && t < (b ? until(b) : e + 6)) cur = a.n;
    });
    return cur || (t < 6 ? 'The pull' : phaseAt(t));
  }
  function phaseAt(t) {
    var p = FV.phases[0][0];
    FV.phases.forEach(function (x, k) {
      if (!k) return;
      var a = N.findIndex(function (n) { return n.k === 'phase' && Math.abs(n.t - x[1]) < 0.6; });
      if (t >= (a >= 0 ? eff(N[a].t) : x[1])) p = x[0];
    });
    return p;
  }
  function nextAnchor(t) { for (var i = 0; i < N.length; i++) if (N[i].k !== 'pull' && !gone(N[i].t) && eff(N[i].t) > t) return i; return -1; }

  /* the boss event a press now confirms: a phase start first (they move with the boss's health), else the closest */
  /* the boss event a press now confirms: the pull while nothing is confirmed yet; a phase start when it is close and
     no other boss event is within a few seconds (phases follow the boss's health); otherwise the closest event */
  function syncTarget(t) {
    var past = lastPt(), c = [];
    N.forEach(function (a, i) {
      if (confirmed(i) || a.t < past || gone(a.t)) return;
      var w = WIN[a.k] || WIN.cast, d = t - eff(a.t);
      if (d >= w[0] && d <= w[1]) c.push({ i: i, d: d, k: a.k });
    });
    if (!c.length) return -1;
    var pull = c.filter(function (x) { return x.k === 'pull'; })[0];
    if (pull && !st.conf.length && t < 10) return pull.i;
    var big = function (x) { return x.k === 'phase' || x.k === 'immune'; };
    var near = c.some(function (x) { return !big(x) && x.k !== 'pull' && Math.abs(x.d) <= NEAR; });
    var ph = c.filter(function (x) { return big(x) && Math.abs(x.d) <= FIRST; }).sort(function (a, b) { return Math.abs(a.d) - Math.abs(b.d); })[0];
    // before its time, a phase waits for an earlier boss event still in its window (a late cast is not the phase)
    var earlier = ph && ph.d < 0 && c.some(function (x) { return !big(x) && x.k !== 'pull' && N[x.i].t < N[ph.i].t; });
    if (ph && !near && !earlier) return ph.i;
    c.sort(function (a, b) { return Math.abs(a.d) - Math.abs(b.d); });
    return c[0].i;
  }

  /* the screen reader hears what the voice says: one write every 1.5 s at most, never the same line twice in 4 s */
  function say(s, voice) {
    if (!s) return;
    var k = s.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').trim(), now = performance.now();
    if (st.said[k] && now - st.said[k] < 4000) return;
    st.said[k] = now;
    if (voice && st.sound && window.speechSynthesis) {
      try { speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance(s); u.rate = 1.1; speechSynthesis.speak(u); } catch (e) { /* no voice */ }
    }
    st.sq.push(s); flush();
  }
  function flush() {
    if (!st.sq.length) return;
    var wait = st.sqAt + 1500 - performance.now();
    if (wait > 0) { clearTimeout(st.sqT); st.sqT = setTimeout(flush, wait); return; }
    $('sr').textContent = st.sq.splice(0).map(function (s) { return s.replace(/[.\s]+$/, ''); }).join('. ') + '.';
    st.sqAt = performance.now();
  }
  function beep() {
    if (!st.sound) return;
    try {
      var C = window.AudioContext || window.webkitAudioContext; st.ac = st.ac || new C();
      var o = st.ac.createOscillator(), g = st.ac.createGain(); o.frequency.value = 880; g.gain.value = 0.08;
      o.connect(g); g.connect(st.ac.destination); o.start(); o.stop(st.ac.currentTime + 0.12);
    } catch (e) { /* no sound */ }
  }

  function set(el, html) { if (el && el.__h !== html) { el.innerHTML = html; el.__h = html; } }
  function txt(el, s) { if (el && el.textContent !== s) el.textContent = s; }

  function render() {
    var t = st.cur, cc = call(t), sh = shift(1e9);
    txt($('c-time'), clock(t)); txt($('ss-clock'), clock(t));
    var ph = phaseAt(t) + (st.conf.length && Math.abs(Math.round(sh)) >= 2 ? ' · boss ' + Math.abs(Math.round(sh)) + ' s ' + (sh > 0 ? 'behind' : 'ahead') : '');
    txt($('c-phase'), ph); txt($('ss-phase'), ph);
    txt($('c-title'), title(t, cc));
    var bl = bossNow(t); txt($('c-boss'), bl); txt($('ss-boss'), bl === '—' ? '' : bl);
    txt($('c-you'), cc.state === 'go' ? names(cc.g) : 'Your rotation');
    ['c-call', 'ss-call'].forEach(function (id) { var el = $(id); set(el, cc.html); el.className = cc.cls; });
    var th = then(t, cc); txt($('c-then'), th); txt($('ss-then'), th);
    var n = nextAnchor(t);
    if (n >= 0) {
      txt($('c-next'), N[n].n + ' '); txt($('c-in'), 'in ' + secs(eff(N[n].t) - t));
      var prev = n > 0 ? eff(N[n - 1].t) : 0;
      $('c-meter').style.transform = 'scaleX(' + Math.min(1, Math.max(0, (t - prev) / Math.max(1, eff(N[n].t) - prev))).toFixed(3) + ')';
    } else if (t < FV.end) {
      txt($('c-next'), 'The kill '); txt($('c-in'), 'around ' + mmss(FV.end)); $('c-meter').style.transform = 'scaleX(0)';
    } else { txt($('c-next'), ''); txt($('c-in'), ''); $('c-meter').style.transform = 'scaleX(0)'; }
    st.target = st.playing ? syncTarget(t) : -1;
    ['c-sync', 'ss-sync'].forEach(function (id) {
      var b = $(id), hide = st.target < 0;
      if (hide && !b.hidden && document.activeElement === b) $(id === 'c-sync' ? 'play' : 'ss-play').focus();
      b.hidden = hide;
      if (!hide) {
        txt(b.firstChild, N[st.target].n + ' started?');
        b.setAttribute('aria-label', N[st.target].n + ' started? Press Control Shift Space');
      }
    });
    if (st.target >= 0 && !st.saidKeys && st.playing) { say('Control Shift Space confirms a boss event when it starts.'); st.saidKeys = true; }
    if (cc.key !== st.key && performance.now() >= st.quietUntil) {
      if (st.playing && cc.say) { say(cc.say, true); if (cc.state === 'go') beep(); }
      st.key = cc.key;
    }
    row(t);
    bars(t);
    playBtn();
  }

  /* the current row: lit, aria-current on its time, that time the only one in the Tab order */
  function row(t) {
    var r = -1;
    FV.rows.forEach(function (rt, i) { if (eff(rt) <= t + 0.01) r = i; });
    if (r === st.curRow) return;
    var old = root.querySelector('.fm.on');
    if (old) { old.classList.remove('on'); old.querySelector('.t').setAttribute('aria-current', 'false'); }
    var el = r >= 0 ? root.querySelector('.fm[data-i="' + r + '"]') : null;
    if (el) {
      el.classList.add('on'); el.querySelector('.t').setAttribute('aria-current', 'true');
      roving(el.querySelector('.t'));
      if (st.playing && performance.now() - st.userScroll > 4000) el.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    }
    st.curRow = r;
  }
  function roving(cur) { root.querySelectorAll('.fm .t').forEach(function (b) { b.tabIndex = b === cur ? 0 : -1; }); }

  /* second screen: what comes in the next minute, yours and the boss's, as bars that empty */
  function bar(e, t, cls, ic, who, n) {
    return [e, '<div class="fbar ' + cls + '" role="listitem"><i class="fill" style="transform:scaleX(' + Math.max(0, Math.min(1, (e - t) / 60)).toFixed(3) + ')"></i>' + icon(ic) + '<b><span class="vh">' + who + ': </span>' + esc(n) + '</b><span>' + (e - t <= 0.5 ? 'now' : secs(e - t)) + '</span></div>'];
  }
  function bars(t) {
    if (!$('ss').open) return;
    var out = [], seen = {};
    var mine = [];
    byEff().forEach(function (a) {
      var e = eff(a.t), k = e.toFixed(0) + a.n;
      if (e < t - 0.5 || e > t + 60 || seen[k]) return;
      seen[k] = 1; mine.push([e, a.n]); out.push(bar(e, t, 'mine', a.ic, 'You', a.n));
    });
    N.forEach(function (a) {
      var e = eff(a.t);
      if (a.k === 'pull' || gone(a.t) || e < t - 0.5 || e > t + 60) return;
      if (mine.some(function (m) { return Math.abs(m[0] - e) <= 1 && m[1].indexOf(a.n) >= 0; })) return;  // "Kill X" says it
      out.push(bar(e, t, 'boss', a.ic, 'Boss', a.n));
    });
    out.sort(function (a, b) { return a[0] - b[0]; });
    set($('ss-bars'), out.slice(0, 7).map(function (x) { return x[1]; }).join('') || '<p class="pend">Nothing in the next minute: your rotation.</p>');
  }

  function playBtn() {
    ['play', 'ss-play'].forEach(function (id) {
      var b = $(id), s = b.querySelector('span'); txt(s || b, st.playing ? 'Pause' : (st.cur !== 0 ? 'Resume' : 'Play'));
    });
    document.body.classList.toggle('playing', st.playing);
    document.body.classList.toggle('paused', !st.playing && st.cur !== 0);
    document.body.classList.toggle('live', st.playing || st.cur !== 0);
  }

  function tick(now) {
    if (!st.playing) return;
    if (st.last != null) st.cur += (now - st.last) / 1000 * st.speed;
    st.last = now;
    if (st.cur > FV.end + 30) { setPlay(false, true); st.cur = 0; st.conf = []; st.key = ''; say('Playback over. Play to start again.'); render(); return; }
    render();
    requestAnimationFrame(tick);
  }
  /* in the desktop app, the same key works while the game has the focus (paf.desktop holds it while a fight plays) */
  function globalKey(on) {
    try {
      var w = window.pywebview ? window : (window.parent && window.parent.pywebview ? window.parent : null);
      if (w && w.pywebview.api && w.pywebview.api.sync_key) w.pywebview.api.sync_key(on);
    } catch (e) { /* a browser: the key works in the page only */ }
  }
  function setPlay(on, quiet) {
    st.playing = on; st.last = null; globalKey(on);
    if (on) requestAnimationFrame(tick);
    if (!quiet) say(on ? 'Playing from ' + clock(st.cur) : 'Paused at ' + clock(st.cur));
    render();
  }
  function pullTimer() {
    if (st.playing) { say('The fight is running: pause or wipe first.'); return; }
    st.cur = -10; st.conf = []; st.key = ''; st.saidKeys = false; setPlay(true, true); say('Pull in 10 seconds.');
  }
  function wipe() { setPlay(false, true); st.cur = 0; st.conf = []; st.key = ''; st.saidKeys = false; render(); say('Wipe: back to the pull.'); }

  /* "it starts now": exactly the boss event the button names */
  function sync() {
    if (!st.playing) { say('Press Play first.'); return; }
    var now = performance.now();
    if (now - st.lastPress < BOUNCE * 1000) { say('Already confirmed.'); return; }
    var i = st.target;
    if (i < 0) { say('Nothing to confirm right now.', true); return; }
    var a = N[i], late = Math.round(st.cur - a.t);
    st.conf = st.conf.filter(function (c) { return c.pt < a.t; });  // what came after it is timed from it now
    N.forEach(function (b, j) {  // the boss events at the same time are confirmed with it
      if (Math.abs(b.t - a.t) <= 1) st.conf.push({ i: j, pt: b.t, at: st.cur + (b.t - a.t), big: b.k === 'phase' || b.k === 'immune' });
    });
    st.lastPress = now; st.quietUntil = now + QUIET * 1000; st.key = '';
    var how = Math.abs(late) <= 2 ? 'on time' : 'boss ' + Math.abs(late) + ' s ' + (late > 0 ? 'behind' : 'ahead of') + ' the plan';
    say(a.n + ' confirmed, ' + how + '.', true);
    render();
  }

  function openSS() {
    st.ssFrom = document.activeElement;
    var dlg = $('ss');
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
    dlg.classList.add('open'); document.body.classList.add('ss-on'); dlg.focus(); render();
  }
  function closeSS() {
    var dlg = $('ss');
    if (dlg.close && dlg.open) dlg.close(); else dlg.removeAttribute('open');
    dlg.classList.remove('open'); document.body.classList.remove('ss-on'); st.curRow = -1; (st.ssFrom || $('ss-open')).focus(); render();
  }

  /* bars along the clock and the "now" marker, from the rows' positions */
  function yAtFn() {
    var tl = $('tl'), base = tl.getBoundingClientRect().top;
    var pts = [].slice.call(tl.querySelectorAll('.fm')).map(function (r) { return [+r.dataset.t, r.getBoundingClientRect().top - base + 14]; })
      .sort(function (a, b) { return a[0] - b[0]; });
    return function (t) {
      if (!pts.length) return 0;
      if (t <= pts[0][0]) return pts[0][1];
      for (var k = 1; k < pts.length; k++) if (t <= pts[k][0]) { var a = pts[k - 1], b = pts[k]; return a[1] + (b[1] - a[1]) * (t - a[0]) / Math.max(0.1, b[0] - a[0]); }
      var l = pts[pts.length - 1]; return l[1] + (t - l[0]) * 2;
    };
  }
  function layout() {
    var tl = $('tl'); if (!tl || !tl.offsetParent) return;
    tl.querySelectorAll('.strip').forEach(function (x) { x.remove(); });
    var yAt = yAtFn(), spine = tl.querySelector('.fm .spine'); if (!spine) return;
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
  $('ss').addEventListener('cancel', function (ev) { ev.preventDefault(); closeSS(); });
  $('ss-wipe').addEventListener('click', wipe);
  $('ss-sound').addEventListener('click', function () {
    st.sound = !st.sound; this.setAttribute('aria-pressed', st.sound); say(st.sound ? 'Voice and beeps on.' : 'Voice and beeps off.', true);
  });
  root.querySelectorAll('.seg [data-s]').forEach(function (b) {
    b.addEventListener('click', function () {
      st.speed = +b.dataset.s; root.querySelectorAll('.seg [data-s]').forEach(function (x) { x.setAttribute('aria-pressed', x === b); });
    });
  });
  var pills = [].slice.call(root.querySelectorAll('.fm .t'));
  pills.forEach(function (b, k) {
    b.tabIndex = k ? -1 : 0;
    b.addEventListener('click', function () {
      var r = b.closest('.fm'), t = eff(+r.dataset.t); st.cur = t; st.key = ''; render();
      say('At ' + clock(t) + ', ' + (r.dataset.title || b.textContent));
    });
    b.addEventListener('keydown', function (ev) {
      var n = { ArrowDown: 1, ArrowUp: -1, Home: -1e9, End: 1e9 }[ev.key]; if (!n) return;
      ev.preventDefault(); var to = pills[Math.max(0, Math.min(pills.length - 1, k + n))]; roving(to); to.focus();
    });
  });
  var mrtB = $('mrt');
  if (mrtB) mrtB.addEventListener('click', function () {
    var box = $('mrt-text'), lab = mrtB.querySelector('span');
    var done = function () { txt(lab, 'Copied'); say('MRT note copied.'); setTimeout(function () { txt(lab, 'Copy as MRT note'); }, 1500); };
    var fallback = function () {
      box.hidden = false; box.select(); var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      if (ok) done(); else { txt(lab, 'Select and copy'); say('Select the note and copy it.'); }
    };
    if (navigator.clipboard) navigator.clipboard.writeText(box.value).then(done, fallback); else fallback();
  });
  document.addEventListener('keydown', function (ev) {
    if (!visible()) return;
    var tag = (ev.target.tagName || '').toLowerCase();
    if (ev.ctrlKey && ev.shiftKey && (ev.code === 'Space' || ev.key === ' ')) { ev.preventDefault(); sync(); return; }
    if (ev.altKey && (ev.key === 'p' || ev.key === 'P')) { ev.preventDefault(); pullTimer(); return; }
    if ((ev.code === 'Space' || ev.key === ' ') && !ev.ctrlKey && !ev.altKey && !ev.metaKey
        && !/^(input|textarea|select|button|a|summary)$/.test(tag) && (root.contains(ev.target) || ev.target === document.body)) {
      ev.preventDefault(); setPlay(!st.playing);
    }
  });
  window.addEventListener('wheel', function () { st.userScroll = performance.now(); }, { passive: true });
  window.addEventListener('keydown', function (ev) { if (/^(PageUp|PageDown|ArrowUp|ArrowDown|Home|End)$/.test(ev.key)) st.userScroll = performance.now(); });
  var lt; window.addEventListener('resize', function () { clearTimeout(lt); lt = setTimeout(layout, 150); });
  if (window.ResizeObserver) new ResizeObserver(function () { clearTimeout(lt); lt = setTimeout(layout, 100); }).observe($('tl'));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
  window.addEventListener('pagehide', function () { globalKey(false); });
  window.__fv = { st: st, render: render, layout: layout, sync: sync, eff: eff };
  layout(); render();
})();
