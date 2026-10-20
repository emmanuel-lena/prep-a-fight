"""The first run (issue #11): a few steps in one page, no reloads, each one skippable, the step remembered.

Welcome, your Warcraft Logs key, your character (found on Warcraft Logs, or a /simc export), your raid, done.
Each form is sent with fetch() to a small JSON route (paf.web: /onboard/<step>) and the page slides to the next
step; without JavaScript the forms still work as plain posts.
"""

from __future__ import annotations

from paf import settings, theme

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


def save_profile(text: str, imported: bool = False) -> dict:
    from paf import characters

    c = characters.save(text, imported)
    return {"ok": True, "name": c.name, "spec": _say(f"{c.spec.title()} {c.class_name.title()}")}


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
    out = save_profile(profile, imported=True)
    out["what"] = _say(what)
    return out


ACCOUNT = """query { userData { currentUser { characters { name server { slug region { slug } } } } } }"""


def account_characters(client=None) -> list[tuple[str, str, str]]:
    """(name, server slug, region) of the characters of the player's Warcraft Logs account, when they logged in
    with it (scope view-user-profile; an older login without it gives none): several at once, no typing."""
    from paf import wcllogin

    if not wcllogin.logged_in():
        return []
    try:
        from paf.wcl import WCLClient

        data = (client or WCLClient()).query(ACCOUNT, {}, cache_ttl=3600)
    except Exception:  # noqa: BLE001 - the search by name stays
        return []
    return characters_of(data)


def characters_of(data: dict) -> list[tuple[str, str, str]]:
    user = ((data or {}).get("userData") or {}).get("currentUser") or {}
    out = []
    for c in user.get("characters") or []:
        srv = c.get("server") or {}
        if c.get("name") and srv.get("slug"):
            out.append((c["name"], srv["slug"], ((srv.get("region") or {}).get("slug") or "eu").lower()))
    return sorted(set(out))


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
    from paf import wcllogin
    from paf.web import connect_block, has_credentials

    regions = "".join(f"<option value='{r}'>{r.upper()}</option>" for r in settings.SETTINGS["guild_region"].choices)
    key_done = has_credentials()
    from html import escape as esc

    from paf.profile import parse_simc_export
    from paf.web import _profile_path

    prof = _profile_path()
    char = parse_simc_export(prof.read_text(encoding="utf-8-sig")) if prof.is_file() else None
    have_char = (f"<p class='ob-have'>Loaded now: <b>{esc(char.name)}, {esc(char.spec.title())} "
                 f"{esc(char.class_name.title())}</b>. Paste another export only to change it.</p>") if char else ""
    guild, gserver, greg = settings.get("guild") or "", settings.get("guild_server") or "", settings.get("guild_region")
    regions_g = "".join(f"<option value='{r}'{' selected' if r == greg else ''}>{r.upper()}</option>"
                        for r in settings.SETTINGS["guild_region"].choices)
    # already set: keep it and go on (a Save that changes nothing, or a "Skip" that sounds like dropping it, is not it)
    # a field changed: the save button takes the primary place and "Keep" goes (see JS), nothing typed is lost
    keep = "<button type='button' class='btn go next keep'>{} &rarr;</button>"
    keep_char = "<button class='btn ghost save-alt' hidden>Load the pasted one</button>" + keep.format("Keep this character")
    keep_char_wcl = ("<button class='btn ghost save-alt' hidden>Find this one instead</button>"
                     + keep.format("Keep this character"))
    keep_guild = "<button class='btn ghost save-alt' hidden>Save changes</button>" + keep.format("Keep it")
    summary = "</li><li>".join(esc(x) for x in (
        ("Warcraft Logs through your account" if wcllogin.logged_in() else "Warcraft Logs through your own API key")
        if key_done else "",
        f"character {char.name}" if char else "",
        f"guild {guild}" if guild else "") if x)  # what is set already, said on the last step
    skip = "<button type='button' class='btn ghost skip'>Skip</button>"
    mine = account_characters()  # logged in with Warcraft Logs: the account's characters, one click each
    acc_tab = "<button type='button' role='tab' class='on' data-tab='acc'>Your account</button>" if mine else ""
    acc_forms = ("<div class='ob-tab' data-tab='acc'><p class='small muted'>Your Warcraft Logs account's characters: "
                 "add one or several (their latest logged boss fight gives their gear and talents; no bags).</p>"
                 "<div class='ob-acc'>" + "".join(
                     f"<form class='ob-form' data-to='/onboard/character' data-stay='1'>"
                     f"<input type='hidden' name='name' value='{esc(n)}'><input type='hidden' name='server' "
                     f"value='{esc(sv)}'><input type='hidden' name='region' value='{esc(rg)}'>"
                     f"<button class='btn ghost'>Add {esc(n)} <small>{esc(sv)}-{esc(rg.upper())}</small></button>"
                     f"<p class='ob-err' role='alert'></p></form>" for n, sv, rg in mine)
                 + "</div><div class='ob-actions'><button type='button' class='btn go next'>Next &rarr;</button>"
                 + skip + "</div></div>") if mine else ""
    key_form = f"""{connect_block() + "<div class='ob-actions'>" + skip + "</div><details class='ob-own' open><summary>Or use your own API key</summary>"
 if wcllogin.available() else ""}
<p>The app reads the top players' logs with <b>your own</b> free Warcraft Logs API key (each player has an hourly quota, so the key is not shared).</p>
<ol class="small"><li>Log in on <a href="https://www.warcraftlogs.com/api/clients" target="_blank" rel="noopener">warcraftlogs.com/api/clients</a> and click <b>Create Client</b>.</li>
<li>Name: anything (e.g. <code>prep-a-fight</code>). Redirect URL: <code>http://localhost</code>. Leave "Public Client" unticked.</li>
<li>Copy the <b>Client ID</b> and the <b>Client Secret</b> here.</li></ol>
<form class="ob-form" data-to="/onboard/key" method="post" action="/credentials">
<input name="id" placeholder="Client ID" required autocomplete="off"><input name="secret" placeholder="Client Secret" required autocomplete="off">
<p class="ob-err" role="alert"></p>
<div class="ob-actions"><button class="btn go">Save and test</button>{skip}</div></form>
{"</details>" if wcllogin.available() else ""}
"""
    via = "your Warcraft Logs account" if wcllogin.logged_in() else "your own API key"
    done_html = (f"<p>The app reads the logs with {via}. Nothing to do here.</p>"  # no connect button then
                 "<div class='ob-actions'><button type='button' class='btn go next'>Next &rarr;</button></div>")
    return f"""<div class="ob" data-key="{'1' if key_done else ''}">
<p class="ob-brand">prep-a-<b>fight</b></p>
<ol class="ob-dots" aria-hidden="true">{''.join('<li></li>' for _ in STEPS[1:-1])}</ol>

<section class="ob-step" data-step="welcome">
<h1>Your boss, prepared on your computer</h1>
<ul class="ob-points"><li><b>What the best players do</b> on this boss, read from their logs.</li>
<li><b>Your character simmed on the real fight</b>, rebuilt from those logs: talents, gear, cooldowns.</li>
<li><b>One sheet</b>: what to change, when to press what, what to watch out for.</li></ul>
<p class="muted">Free, on your computer. Three short steps, then you are ready; skip any of them, everything is in Settings later.</p>
<div class="ob-actions"><button type="button" class="btn go next">Start &rarr;</button>
<a class="btn ghost" href="/onboard/skip">Skip all</a></div></section>

<section class="ob-step" data-step="key">
<h1>{'Warcraft Logs: ready' if key_done else 'Connect to Warcraft Logs' if wcllogin.available() else 'Your Warcraft Logs key'}</h1>
{done_html if key_done else key_form}</section>

<section class="ob-step" data-step="character">
<h1>Your character</h1>{have_char}
<div class="ob-tabs" role="tablist">{acc_tab}<button type="button" role="tab"{'' if mine else ' class="on"'} data-tab="simc" title="Recommended: it includes your bags">Paste /simc</button>
<button type="button" role="tab" data-tab="wcl">Find by name</button></div>{acc_forms}
<form class="ob-form ob-tab" data-tab="wcl" data-to="/onboard/character" hidden>
<p class="small muted">Its latest logged boss fight gives its gear and talents. No bags: for Top Gear, paste /simc.</p>
<div class="row"><input name="name" placeholder="Character name" required><input name="server" placeholder="Server" required>
<select name="region" aria-label="Region">{regions}</select></div>
<p class="ob-err" role="alert"></p>
<div class="ob-actions">{keep_char_wcl if char else '<button class="btn go">Find my character</button>' + skip}</div></form>
<form class="ob-form ob-tab" data-tab="simc" data-to="/onboard/simc" method="post" action="/profile"{' hidden' if mine else ''}>
<p class="small muted">In game: type <code>/simc</code>, then Ctrl+A, Ctrl+C, and paste here (it includes your bags).</p>
<textarea name="simc" required placeholder="Paste the /simc export here"></textarea>
<p class="ob-err" role="alert"></p>
<div class="ob-actions">{keep_char if char else '<button class="btn go">Load this character</button>' + skip}</div></form></section>

<section class="ob-step" data-step="raid">
<h1>Your guild <span class="pill">optional</span></h1>
<p>Your guild's latest public log tells the prep who plays what in your raid: whether the others cover the adds
(stay on the boss) or you should pad them, and how your last pull compares with the top players'.</p>
<form class="ob-form" data-to="/onboard/raid" method="post" action="/guild">
<div class="row ob-labelled"><label>Guild<input name="guild" placeholder="Guild name" value="{esc(guild)}"></label>
<label>Server<input name="server" placeholder="Server" value="{esc(gserver)}"></label>
<label>Region<select name="region">{regions_g}</select></label></div>
<p class="ob-err" role="alert"></p>
<div class="ob-actions">{keep_guild if guild else '<button class="btn go">Save</button>' + skip}</div></form></section>

<section class="ob-step" data-step="done">
<h1>Ready</h1>
{f"<p>Already set:</p><ul class='ob-set'><li>{summary}</li></ul>" if summary else ""}
<p class="ob-summary muted" data-title="Guild saved" data-text="{'Everything can be changed later in Settings.' if summary else 'You can set the rest later in Settings.'}"></p>
<div class="ob-actions"><a class="btn go finish" href="/onboard/finish">Prepare a boss &rarr;</a></div></section>
</div>"""


CSS = theme.style("onboarding")

JS = """<script>
(function(){
var root = document.querySelector('.ob'); if (!root) return;
var steps = [].slice.call(root.querySelectorAll('.ob-step')), dots = [].slice.call(root.querySelectorAll('.ob-dots li'));
var names = steps.map(function(s){ return s.dataset.step; }), at = 0, done = {};
var typed = false;  // something typed and not saved: leaving or reloading asks first
window.addEventListener('beforeunload', function(ev){ if (typed) { ev.preventDefault(); ev.returnValue = ''; } });
root.querySelectorAll('form').forEach(function(f){ f.addEventListener('submit', function(){ typed = false; }); });
root.querySelectorAll('form').forEach(function(f){ f.addEventListener('input', function(){  // an edit: save it first
  typed = true;
  var k = f.querySelector('.keep'), s = f.querySelector('.save-alt'); if (!k || !s) return;
  s.hidden = false; s.classList.remove('ghost'); s.classList.add('go');
  k.classList.remove('go'); k.classList.add('ghost'); k.innerHTML = 'Keep the saved one &rarr;';
  var g = f.querySelector('input[name=guild]');  // an emptied guild saves "no guild": said so
  if (g && s.dataset.label == null) s.dataset.label = s.textContent;
  if (g) s.textContent = g.value.trim() ? s.dataset.label : 'Save without a guild'; }); });
function store(i){ try { localStorage.setItem('paf-onboard', names[i]); } catch (e) {} }
function show(i, back){
  at = Math.max(0, Math.min(steps.length - 1, i));
  steps.forEach(function(s, j){ s.classList.toggle('on', j === at); s.classList.toggle('back', !!back); });
  dots.forEach(function(d, j){ d.classList.toggle('on', j < at); });  // the welcome is not a step
  store(at); var f = steps[at].querySelector('input:not([type=hidden]),textarea');  // a field, never a tab or a button
  if (f) f.focus({preventScroll: true});
  if (names[at] === 'done') summary();
}
function next(){ show(at + 1); }
function summary(){
  var el = root.querySelector('.ob-summary'), s = [];
  if (done.character) s.push(done.character); if (done.raid) s.push(el.dataset.title);
  el.textContent = s.length ? s.join(' \\u00b7 ') : el.dataset.text;
}
root.querySelectorAll('.next,.skip').forEach(function(b){ b.addEventListener('click', next); });
root.querySelectorAll('.wcl-connect').forEach(function(c){ c.addEventListener('wcl-connected', function(ev){
  ev.preventDefault(); done.key = true; next(); }); });
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
      if (f.dataset.stay) {  // one of several: marked added, the step stays for the others
        var b = f.querySelector('button'); b.disabled = true; b.textContent = 'Added: ' + j.name + ' (' + j.spec + ')';
        done[step] = (done[step] && done[step] !== true ? done[step] + ', ' : '') + j.name; return; }
      done[step] = j.what || (j.name ? j.name + ' (' + j.spec + ')' : true); next(); })
    .catch(function(){ f.classList.remove('busy'); err.textContent = 'The app did not answer: try again.'; });
}); });
var saved = ''; try { saved = localStorage.getItem('paf-onboard') || ''; } catch (e) {}
show(Math.max(0, names.indexOf(saved)));
})();
</script>"""
