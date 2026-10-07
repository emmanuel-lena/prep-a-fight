"""The first run (issue #11): a few steps in one page, no reloads, each one skippable, the step remembered.

Welcome, your Warcraft Logs key, your character (found on Warcraft Logs, or a /simc export), your raid, done.
Each form is sent with fetch() to a small JSON route (paf.web: /onboard/<step>) and the page slides to the next
step; without JavaScript the forms still work as plain posts.
"""

from __future__ import annotations

from paf import settings

STEPS = ("welcome", "key", "character", "raid", "done")


def needed() -> bool:
    """Show the steps: never done nor skipped, and the app is not set up yet."""
    from paf.web import _profile_path, has_credentials

    return settings.get("onboarded") != "on" and not (has_credentials() and _profile_path().is_file())


def save_key(cid: str, secret: str) -> dict:
    from paf.config import save_credentials
    from paf.wcl import WCLClient, WCLError

    cid, secret = cid.strip(), secret.strip()
    try:
        WCLClient(cid, secret).rate_limit()
    except (WCLError, OSError) as ex:
        return {"ok": False, "error": _say(f"Warcraft Logs refused this key: {ex}")}
    save_credentials(cid, secret)
    return {"ok": True}


def save_profile(text: str) -> dict:
    from paf.profile import parse_simc_export, use_profile_spec
    from paf.web import _profile_path

    p = _profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
    prof = parse_simc_export(text)
    use_profile_spec(prof)
    return {"ok": True, "name": prof.name, "spec": f"{prof.spec.title()} {prof.class_name.title()}"}


def find_character(name: str, server: str, region: str) -> dict:
    from paf.character import import_character
    from paf.wcl import WCLClient, WCLError
    from paf.web import has_credentials

    if not has_credentials():
        return {"ok": False, "error": _say("Add your Warcraft Logs key first (the step before), or paste your /simc export.")}
    try:
        profile, what = import_character(WCLClient(), name, server, region)
    except (ValueError, WCLError, OSError, KeyError, TypeError) as ex:
        return {"ok": False, "error": _say(str(ex))}
    out = save_profile(profile)
    out["what"] = _say(what)
    return out


def _say(text: str) -> str:
    """A sentence of a JSON answer in the player's language (pages are translated when sent, JSON is not)."""
    from html import escape, unescape

    from paf.i18n import translate

    return unescape(translate(escape(text)))


def paste_simc(text: str) -> dict:
    from paf.profile import looks_like_export

    if not looks_like_export(text):
        return {"ok": False, "error": _say("That does not look like a /simc export.")}
    return save_profile(text)


def save_raid(guild: str, server: str, region: str) -> dict:
    settings.set_value("guild", guild.strip())
    settings.set_value("guild_server", server.strip())
    settings.set_value("guild_region", (region or "eu").strip().lower())
    return {"ok": True}


def finish() -> dict:
    settings.set_value("onboarded", "on")
    return {"ok": True}


def page_body() -> str:
    from paf.web import has_credentials

    regions = "".join(f"<option>{r}</option>" for r in settings.SETTINGS["guild_region"].choices)
    key_done = has_credentials()
    skip = "<button type='button' class='btn ghost skip'>Skip</button>"
    return f"""<div class="ob" data-key="{'1' if key_done else ''}">
<ol class="ob-dots" aria-hidden="true">{''.join('<li></li>' for _ in STEPS)}</ol>

<section class="ob-step" data-step="welcome">
<h1>Your boss, prepared in a few minutes</h1>
<ul class="ob-points"><li><b>What the best players do</b> on this boss, read from their logs.</li>
<li><b>Your character simmed on the real fight</b>, rebuilt from those logs: talents, gear, cooldowns.</li>
<li><b>One sheet</b>: what to change, when to press what, what to watch out for.</li></ul>
<p class="muted">Free, on your computer. Four short steps; skip any of them, everything is in Settings later.</p>
<div class="ob-actions"><button type="button" class="btn go next">Start &rarr;</button>
<a class="btn ghost" href="/onboard/skip">Skip all</a></div></section>

<section class="ob-step" data-step="key">
<h1>Your Warcraft Logs key</h1>
<p>The app reads the top players' logs with <b>your own</b> free Warcraft Logs API key (each player has an hourly quota, so the key is not shared).</p>
<ol class="small"><li>Log in on <a href="https://www.warcraftlogs.com/api/clients" target="_blank" rel="noopener">warcraftlogs.com/api/clients</a> and click <b>Create Client</b>.</li>
<li>Name: anything (e.g. <code>prep-a-fight</code>). Redirect URL: <code>http://localhost</code>. Leave "Public Client" unticked.</li>
<li>Copy the <b>Client ID</b> and the <b>Client Secret</b> here.</li></ol>
<form class="ob-form" data-to="/onboard/key" method="post" action="/credentials">
<input name="id" placeholder="Client ID" required autocomplete="off"><input name="secret" placeholder="Client Secret" required autocomplete="off">
<p class="ob-err" role="alert"></p>
<div class="ob-actions"><button class="btn go">Save and test</button>{skip}</div></form>
<p class="ob-ok-note muted small">{'A key is already saved: you can go on.' if key_done else ''}</p></section>

<section class="ob-step" data-step="character">
<h1>Your character</h1>
<div class="ob-tabs" role="tablist"><button type="button" role="tab" class="on" data-tab="wcl">Find it on Warcraft Logs</button>
<button type="button" role="tab" data-tab="simc">Paste /simc</button></div>
<form class="ob-form ob-tab" data-tab="wcl" data-to="/onboard/character">
<p class="small muted">Its latest logged boss fight gives its gear and talents. No bags: for Top Gear, paste /simc.</p>
<div class="row"><input name="name" placeholder="Character name" required><input name="server" placeholder="Server" required>
<select name="region" aria-label="Region">{regions}</select></div>
<p class="ob-err" role="alert"></p>
<div class="ob-actions"><button class="btn go">Find my character</button>{skip}</div></form>
<form class="ob-form ob-tab" data-tab="simc" data-to="/onboard/simc" hidden method="post" action="/profile">
<p class="small muted">In game: type <code>/simc</code>, then Ctrl+A, Ctrl+C, and paste here (it includes your bags).</p>
<textarea name="simc" required placeholder="Paste the /simc export here"></textarea>
<p class="ob-err" role="alert"></p>
<div class="ob-actions"><button class="btn go">Load this character</button>{skip}</div></form></section>

<section class="ob-step" data-step="raid">
<h1>Your raid <span class="pill">optional</span></h1>
<p>Your guild's latest public log tells the prep who plays what in your raid: whether the others cover the adds
(stay on the boss) or you should pad them, and how your last pull compares with the top players'.</p>
<form class="ob-form" data-to="/onboard/raid" method="post" action="/guild">
<div class="row"><input name="guild" placeholder="Guild name"><input name="server" placeholder="Server">
<select name="region" aria-label="Region">{regions}</select></div>
<p class="ob-err" role="alert"></p>
<div class="ob-actions"><button class="btn go">Save</button>{skip}</div></form></section>

<section class="ob-step" data-step="done">
<h1>Ready</h1>
<p class="ob-summary" data-title="your raid is saved" data-text="You can set the rest later in Settings."></p>
<div class="ob-actions"><a class="btn go finish" href="/onboard/finish">Prepare a boss &rarr;</a></div></section>
</div>"""


CSS = """
.ob{max-width:620px;margin:20px auto;position:relative}
.ob-dots{display:flex;gap:8px;list-style:none;padding:0;margin:0 0 26px}
.ob-dots li{width:34px;height:5px;border-radius:3px;background:var(--line);transition:background .3s}
.ob-dots li.on{background:var(--accent)}
.ob-step{display:none}
.ob-step.on{display:block;animation:ob-in .45s cubic-bezier(.2,.8,.2,1)}
.ob-step.back.on{animation-name:ob-back}
@keyframes ob-in{from{opacity:0;transform:translateX(28px)}to{opacity:1;transform:none}}
@keyframes ob-back{from{opacity:0;transform:translateX(-28px)}to{opacity:1;transform:none}}
.ob h1{font:600 32px/1.15 'Fraunces',Georgia,serif;margin:0 0 14px}
.ob p,.ob li{font-size:16.5px;line-height:1.55}
.ob-points{padding-left:20px;display:grid;gap:8px;margin:0 0 16px}
.ob-actions{display:flex;gap:10px;align-items:center;margin-top:18px;flex-wrap:wrap}
.ob .btn.go{font-size:17px;padding:11px 24px;border-radius:12px}
.ob form input,.ob form select{font-size:16px;padding:10px 12px}
.ob form .row{display:flex;gap:8px;flex-wrap:wrap} .ob form .row input{flex:1;min-width:140px}
.ob form>input{display:block;width:100%;margin:0 0 8px;box-sizing:border-box}
.ob textarea{width:100%;min-height:160px;box-sizing:border-box}
.ob-err{color:var(--neg);min-height:1.2em;margin:8px 0 0}
.ob-tabs{display:flex;gap:6px;margin:0 0 14px}
.ob-tabs button{border:1.5px solid var(--line);background:none;color:var(--fg);border-radius:999px;padding:8px 16px;
  cursor:pointer;font:inherit;font-weight:600}
.ob-tabs button.on{background:var(--accent);border-color:var(--accent);color:var(--bg)}
.ob .busy{opacity:.6;pointer-events:none}
.ob-summary{font-size:18px}
@media (prefers-reduced-motion:reduce){.ob-step.on{animation:none}}
"""

JS = """<script>
(function(){
var root = document.querySelector('.ob'); if (!root) return;
var steps = [].slice.call(root.querySelectorAll('.ob-step')), dots = [].slice.call(root.querySelectorAll('.ob-dots li'));
var names = steps.map(function(s){ return s.dataset.step; }), at = 0, done = {};
function store(i){ try { localStorage.setItem('paf-onboard', names[i]); } catch (e) {} }
function show(i, back){
  at = Math.max(0, Math.min(steps.length - 1, i));
  steps.forEach(function(s, j){ s.classList.toggle('on', j === at); s.classList.toggle('back', !!back); });
  dots.forEach(function(d, j){ d.classList.toggle('on', j <= at); });
  store(at); var f = steps[at].querySelector('input,textarea,button'); if (f) f.focus({preventScroll: true});
  if (names[at] === 'done') summary();
}
function next(){ show(at + 1); }
function summary(){
  var el = root.querySelector('.ob-summary'), s = [];
  if (done.character) s.push(done.character); if (done.raid) s.push(el.dataset.title);
  el.textContent = s.length ? s.join(' \\u00b7 ') : el.dataset.text;
}
root.querySelectorAll('.next,.skip').forEach(function(b){ b.addEventListener('click', next); });
root.querySelectorAll('.ob-tabs button').forEach(function(b){ b.addEventListener('click', function(){
  root.querySelectorAll('.ob-tabs button').forEach(function(x){ x.classList.toggle('on', x === b); });
  root.querySelectorAll('.ob-tab').forEach(function(f){ f.hidden = f.dataset.tab !== b.dataset.tab; }); }); });
root.querySelectorAll('.ob-form').forEach(function(f){ f.addEventListener('submit', function(ev){
  ev.preventDefault(); var err = f.querySelector('.ob-err'); err.textContent = ''; f.classList.add('busy');
  fetch(f.dataset.to, {method: 'POST', body: new URLSearchParams(new FormData(f))})
    .then(function(r){ return r.json(); })
    .then(function(j){ f.classList.remove('busy');
      if (!j.ok) { err.textContent = j.error || 'Something went wrong.'; return; }
      var step = f.closest('.ob-step').dataset.step;
      done[step] = j.what || (j.name ? j.name + ' (' + j.spec + ')' : true); next(); })
    .catch(function(){ f.classList.remove('busy'); err.textContent = 'The app did not answer: try again.'; });
}); });
var saved = ''; try { saved = localStorage.getItem('paf-onboard') || ''; } catch (e) {}
show(Math.max(0, names.indexOf(saved)));
})();
</script>"""
