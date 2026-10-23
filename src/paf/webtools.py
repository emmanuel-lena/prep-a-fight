"""Every `paf` command in the app: a form per command, built from its command-line options (nothing to keep
in sync by hand), run as a job like the prep; and the settings / status page."""

from __future__ import annotations

import argparse
import html
import os
import re

from paf import __version__, settings
from paf.config import data_dir

e = html.escape

GROUPS = (
    ("Prepare a boss", ("prep", "raid", "review", "comp", "wipe", "night", "diff", "rotation", "raidplan",
                        "timeline", "mechanics", "assigns")),
    ("Sims on the fight", ("topgear", "droptimizer", "bonusroll", "talents", "specgear", "optimize", "cdplan",
                           "plan", "sim")),
    ("The fight model", ("corpus", "analyze", "template", "calibrate", "validate")),
    ("Maintenance", ("setup", "doctor")),
)
SKIP_OPTIONS = {"help", "profile", "simc"}  # the app uses the loaded character and the installed simc


def subparsers() -> dict[str, argparse.ArgumentParser]:
    from paf.cli import build_parser

    parser = build_parser()
    for a in parser._actions:  # noqa: SLF001 - argparse has no public way to list subcommands
        if isinstance(a, argparse._SubParsersAction):  # noqa: SLF001
            return dict(a.choices)
    return {}


def _help(name: str) -> str:
    from paf.cli import build_parser

    for a in build_parser()._actions:  # noqa: SLF001
        if isinstance(a, argparse._SubParsersAction):  # noqa: SLF001
            for c in a._choices_actions:  # noqa: SLF001
                if c.dest == name:
                    return c.help or ""
    return ""


def raw_index() -> str:
    """Every command, raw (the workshop's "for the curious"): its name, its help, all its options."""
    cmds = subparsers()
    out = []
    for title, names in GROUPS:
        tiles = "".join(f'<a class="tile" href="/tool/{n}?raw=1"><b>{e(n)}</b><div class="small muted">{e(_help(n))}'
                        f"</div></a>" for n in names if n in cmds)
        out.append(f"<h3>{e(title)}</h3><div class='grid'>{tiles}</div>")
    return "".join(out)


def advanced_fields(name: str, encounters: list, skip: set[str]) -> str:
    """The options of a command that a workshop form does not set itself."""
    sp = subparsers().get(name)
    if sp is None:
        return ""
    return "".join(_field(a, encounters) for a in sp._actions  # noqa: SLF001
                   if a.dest not in SKIP_OPTIONS and a.dest not in skip and a.dest != "open"
                   and a.help != argparse.SUPPRESS)  # hidden options (set by the app itself) stay hidden


def _field(a: argparse.Action, encounters: list) -> str:
    label = (a.option_strings[-1] if a.option_strings else a.dest).lstrip("-").replace("_", " ").replace("-", " ")
    help_ = f"<span class='tiny muted'>{e(a.help or '')}</span>" if a.help else ""
    name = e(a.dest)
    if isinstance(a, argparse._StoreTrueAction):  # noqa: SLF001
        return f"<label><input type='checkbox' name='{name}'> {e(label)} {help_}</label>"
    if a.dest == "boss" and encounters:
        opts = "".join(f"<option value='{x.id}'>{e(x.name)}</option>" for x in encounters)
        return f"<label>{e(label)} <select name='{name}'>{opts}</select></label>"
    if a.dest == "difficulty":
        cur = settings.get("difficulty")
        opts = "".join(f"<option{' selected' if d == cur else ''}>{d}</option>" for d in settings.DIFFICULTIES)
        return f"<label>{e(label)} <select name='{name}'>{opts}</select> {help_}</label>"
    if a.choices:
        opts = "<option value=''>(default)</option>" + "".join(f"<option>{e(str(c))}</option>" for c in a.choices)
        return f"<label>{e(label)} <select name='{name}'>{opts}</select> {help_}</label>"
    req = " required" if not a.option_strings and a.nargs not in ("?", "*") else ""
    ph = f" placeholder='{e(str(a.default))}'" if a.default not in (None, False, "") else ""
    return f"<label>{e(label)} <input name='{name}'{ph}{req} style='min-width:260px'> {help_}</label>"


def tool_page(name: str, encounters: list) -> str | None:
    sp = subparsers().get(name)
    if sp is None or name in ("serve", "profile", "config"):
        return None
    fields = "".join(_field(a, encounters) for a in sp._actions if a.dest not in SKIP_OPTIONS  # noqa: SLF001
                     and a.help != argparse.SUPPRESS)
    return (f"<p class='small'><a href='/tools'>&larr; Tools</a></p><h1>{e(name)}</h1>"
            f"<p class='lead'>{e(_help(name))}</p><form method='post' action='/tool/{e(name)}' class='card'>"
            f"{fields}<div class='cta'><button class='btn big'>Run</button>"
            f"<span class='small muted'>Runs on your computer; you can follow it live.</span></div></form>")


def tool_args(name: str, form: dict[str, list[str]]) -> list[str] | None:
    """The command line of a submitted tool form (None if the command is unknown)."""
    sp = subparsers().get(name)
    if sp is None:
        return None
    args = [name]
    for a in sp._actions:  # noqa: SLF001
        if a.dest in SKIP_OPTIONS:
            continue
        value = (form.get(a.dest) or [""])[0].strip()
        if isinstance(a, argparse._StoreTrueAction):  # noqa: SLF001
            if a.dest in form:
                args.append(a.option_strings[-1])
        elif value:
            args += [a.option_strings[-1], value] if a.option_strings else [value]
    return args


def new_reports(since: float) -> list[str]:
    reports = data_dir() / "reports"
    return sorted((f.name for f in reports.glob("*.html") if f.stat().st_mtime >= since - 1), reverse=True) \
        if reports.is_dir() else []


# The settings form, for a player: (group, folded, [(key, label, help)]). The keys and their terse help stay those of
# `paf config` (paf.settings); a key missing here goes to the folded group.
SETTINGS_FORM: list[tuple[str, bool, list[tuple[str, str, str]]]] = [
    ("Your raid", False, [
        ("difficulty", "Difficulty", ""),
        ("guild", "Guild", "Its latest public log: who plays what in your raid (pad the adds or not), and your "
                           "last pull against the top players'."),
        ("guild_server", "Guild's server", "As the game writes it (Kazzak, Twisting Nether)."),
        ("guild_region", "Guild's region", ""),
    ]),
    ("The app", False, [
        ("refresh_after_reset", "Prepare again after the weekly reset",
         "Re-runs last week's \"Prepare the whole raid\" bosses after the reset."),
        ("share_packs", "Share the prep packs you compute",
         "Fight data only, no names: the next player of your spec skips the log download."),
        ("check_updates", "Look for new versions", "Every 10 minutes, on GitHub."),
    ]),
    ("Advanced", True, [
        ("corpus_size", "Kills read per boss", "The top kills a prep reads, then keeps reading in the background."),
        ("corpus_points", "Quota for background reading",
         "Warcraft Logs points per hour (of 3,600) the reading in the background may use; a prep you wait for "
         "uses the whole quota."),
        ("region", "Rankings from one region only", ""),
        ("cache_max_mb", "Disk cache cap (MB)", "Sim results and Warcraft Logs answers; the oldest go first."),
    ]),
]


SHOWN_HELP = {"share_packs": "Fight data only, no names."}  # what leaves the computer: always in sight
PLACEHOLDER = {"guild_server": "as the game writes it: Kazzak, Twisting Nether"}


def _setting_control(key: str) -> str:
    s, cur = settings.SETTINGS[key], settings.get(key)
    if key == "region":  # a dropdown, as the guild's region above it
        regs = ("",) + tuple(settings.SETTINGS["guild_region"].choices)
        return "<select name='region' id='s-region'>" + "".join(
            f"<option value='{e(r)}'{' selected' if r == (cur or '') else ''}>{e(r.upper() or 'All regions')}</option>"
            for r in regs) + "</select>"
    if key == "language":  # the languages the app has a catalog for
        from paf.i18n import available

        return f"<select name='{e(key)}' id='s-{e(key)}'>" + "".join(
            f"<option value='{e(c)}'{' selected' if c == cur else ''}>{e(n)}</option>"
            for c, n in {"auto": "Windows' language", **available()}.items()) + "</select>"
    if s.choices == ("on", "off"):  # the hidden "off" goes first: a checked box sends "on" after it (the last wins)
        return (f"<input type='hidden' name='{e(key)}' value='off'><input type='checkbox' name='{e(key)}' "
                f"id='s-{e(key)}' value='on'{' checked' if cur == 'on' else ''}>")
    if s.choices:
        return f"<select name='{e(key)}' id='s-{e(key)}'>" + "".join(
            f"<option value='{e(c)}'{' selected' if c == cur else ''}>"
            f"{e(c.upper() if len(c) <= 3 else c.capitalize())}</option>"  # EU, LFR, Heroic
            for c in s.choices  # no LFR to pick, as on every other page
            if not (key == "difficulty" and c == "lfr" and cur != "lfr")) + "</select>"
    kind = " inputmode='numeric'" if s.kind is int else ""
    ph = f" placeholder='{e(PLACEHOLDER[key])}'" if key in PLACEHOLDER else ""
    return f"<input name='{e(key)}' id='s-{e(key)}' value='{e(str(cur))}'{kind}{ph}>"


def settings_form() -> str:
    """The settings, grouped and in words, with one Save."""
    # set elsewhere, never typed: the class and spec follow the active character, the last raids read are ticked
    # per character in Characters
    listed = {k for _g, _f, rows in SETTINGS_FORM for k, _l, _h in rows}
    listed |= {"class", "spec", "auto_logs", "language", "onboarded"}  # set elsewhere; onboarded: a link
    groups = [(g, folded, [r for r in rows if r[0] in settings.SETTINGS]) for g, folded, rows in SETTINGS_FORM]
    groups[-1][2].extend((k, k.replace("_", " ").capitalize(), s.help) for k, s in settings.SETTINGS.items()
                         if k not in listed)
    out = ""
    for group, _folded, rows in groups:
        def row(k: str, label: str, help_: str) -> str:
            check = settings.SETTINGS[k].choices == ("on", "off")  # a checkbox goes before its label
            # the help on hover, not a line under each row (the owner, 2026-10-24); what is shared stays said
            title = f" title='{e(help_)}'" if help_ else ""
            lab, ctl = f"<label for='s-{e(k)}'{title}>{e(label)}</label>", _setting_control(k)
            return (f"<div class='set-row{' set-check' if check else ''}'>" + (ctl + lab if check else lab + ctl)
                    + (f"<p class='set-help'>{e(SHOWN_HELP[k])}</p>" if k in SHOWN_HELP else "") + "</div>")
        fields = "".join(row(k, label, help_) for k, label, help_ in rows)
        out += f"<fieldset class='set-group'><legend>{e(group)}</legend>{fields}</fieldset>"  # nothing folded
    return out


def short_path(path: str, width: int = 22) -> str:  # 22 mono characters fit the Status column
    """A path cut at its start to fit the Status column, its end kept (the program's name is the part one checks):
    "C:\\Users\\x\\AppData\\Local\\paf\\simc\\simc.exe" -> "…\\paf\\simc\\simc.exe"."""
    if len(path) <= width:
        return path
    sep = "\\" if "\\" in path else "/"
    parts, out = path.split(sep), ""
    for part in reversed(parts):
        if out and len(part) + 1 + len(out) + 2 > width:  # "…" and the separator count too
            break
        out = part + (sep + out if out else "")
    return "…" + sep + out


def path_html(path: str) -> str:
    """A path in the Status table: its end, the whole one on hover or keyboard focus (and selectable to copy)."""
    short = short_path(path)
    if short == path:
        return f"<span class='path'>{e(path)}</span>"
    return (f"<span class='path cut' tabindex='0' title='{e(path)}'><span class='p-short'>{e(short)}</span>"
            f"<span class='p-full'>{e(path)}</span></span>")


OK_DOT = "<span class='ok-dot' aria-hidden='true'>&#10003;</span>"  # a Status row that works


def meter(share: float, calm: bool = False) -> str:
    """A small gauge (the quota spent, the cache filled): warm past three quarters, unless calm (the cache prunes
    itself: full is no alarm)."""
    x = max(0.0, min(1.0, share))
    kind = " calm" if calm else " hi" if x >= 0.75 else ""
    return (f"<span class='meter{kind}' aria-hidden='true'><span style='width:{x * 100:.0f}%'>"
            "</span></span>")


def quota_html() -> str:
    """The Warcraft Logs quota line of Settings, or why it cannot be read."""
    try:
        from paf.wcl import quota_line

        line = quota_line()
        m = re.match(r"([\d,]+) / ([\d,]+)", line)  # thousands written "3,600" (app round 15: the bar read 31/3)
        n = [int(x.replace(",", "")) for x in m.groups()] if m else []
        return (meter(n[0] / max(1, n[1])) if n else "") + e(line)  # a bar beside the numbers
    except Exception as ex:  # noqa: BLE001 - shown as is
        return f"<span class='neg'>{e(str(ex)[:160])}</span>"


def settings_page(message: str = "") -> str:
    from paf.cache import cache_root, size

    cache_meter = meter(size(cache_root()) / 1e6 / max(1.0, float(settings.get("cache_max_mb") or 1)), calm=True)
    from paf.simc_install import find_simc

    exe = find_simc(None)
    simc = path_html(str(exe)) if exe else "<span class='neg'>not installed</span>"
    ok_simc = OK_DOT if exe else ""  # a check only when it holds
    from paf.wcl import fresh_quota
    from paf.web import has_credentials

    ok_wcl = OK_DOT if fresh_quota() or has_credentials() else ""  # a key or a login set
    # a recent read says it at once; else the line comes from /wcl/quota after the page is shown (issue #30)
    quota = quota_html() if fresh_quota() else (
        "<span class='quota-line muted'>reading&hellip;</span><script>fetch('/wcl/quota').then(function(r){"
        "return r.text()}).then(function(t){document.querySelector('.quota-line').outerHTML=t})"
        ".catch(function(){})</script>")
    msg = f"<p class='notice small' role='status'>{e(message)}</p>" if message else ""
    from paf import wcllogin
    from paf.web import connect_block

    cid = os.environ.get("WCL_CLIENT_ID", "")
    # the saved key shown in its own field, so empty fields never read as "no key" (fresh app review 4)
    key_ph = f' placeholder="{e(cid[:8])}… saved"' if cid else ""
    current = ("" if cid else
               "Not used: the app goes through your Warcraft Logs login." if wcllogin.logged_in() else
               "<span class='neg'>No key yet.</span>")
    if wcllogin.logged_in():
        account = ("<p class='small'>Connected with your Warcraft Logs account.</p><form method='post' "
                   "action='/wcl/logout'><button class='btn ghost'>Disconnect</button></form>")
    elif cid:  # the key works already: connecting is an option under it, not the page's action
        account = ""
    else:
        account = connect_block(lead=False)
    alt = ("<hr class='set-hr'>" + connect_block(lead=False, ghost=True)) if cid and not wcllogin.logged_in() \
        and wcllogin.available() else ""
    account = (f"<h2>Warcraft Logs</h2><div class='set-wcl'>{account}<hr class='set-hr'>" if account else "")
    said = ["SimulationCraft installed" if exe else "SimulationCraft <b>not installed</b> (Get nightly, below)"]
    said.append("Warcraft Logs connected with your account" if wcllogin.logged_in() else
                "Warcraft Logs read with your own key" if cid else "Warcraft Logs <b>not connected</b> (below)")
    ok = exe and (wcllogin.logged_in() or cid)
    lead = "All set." if ok else f"Not ready yet: {', '.join(said)}."  # set: the Status table says it (review 6)
    return f"""<h1>Settings</h1><p class="lead">{lead}</p>
{msg}<div class="set-cols"><div>
<form method="post" action="/settings" class="settings">{settings_form()}
<div class="cta"><button class="btn go">Save</button><span class="dirty-note">Unsaved changes</span></div></form>
<p class="muted"><a href="/welcome">Show the welcome steps again</a></p>
</div><div>
{account if account else "<h2>Warcraft Logs</h2><div class='set-wcl'>"}\
{'<h3 class="key-h">Your own API key</h3>' if account else ''}
<p class="small measure">{current} <a href="https://www.warcraftlogs.com/api/clients"
target="_blank" rel="noopener">Use another key &#8599;</a></p>
<form method="post" action="/credentials" class="row"><input type="hidden" name="back" value="settings">
<label class="key-l">Client ID<input name="id" class="key-in" required{key_ph}></label>
<label class="key-l">Client Secret<input name="secret" class="key-in"
type="password" required autocomplete="off"{' placeholder="saved"' if cid else ''}></label>
<button class="btn ghost">{"Replace and test" if cid else "Save and test"}</button></form>
<p class="tiny muted">Saved on this computer only, in {e(str(data_dir() / '.env'))}.</p>{alt}</div>
<h2>Status</h2><div class="set-status"><table class="status">
<tr><td>{ok_simc}SimulationCraft</td><td class="small"><div class="val">{simc}
<form method="post" action="/tool/setup">
<button class="btn ghost" title="Downloads the latest SimulationCraft nightly into the app; a build of your own
stays where it is">Get nightly</button></form></div></td></tr>
<tr><td>{OK_DOT}prep-a-fight</td><td class="small"><div class="val"><span>version {e(__version__)}</span>
<form method="post" action="/update/check"><button class="btn ghost">Check for updates</button></form></div></td></tr>
<tr><td>{ok_wcl}Warcraft Logs</td><td class="small">{quota}</td></tr>
<tr><td>Caches (sims, logs)</td><td class="small">{cache_meter}{size(cache_root()) / 1e6:,.0f} /
{float(settings.get('cache_max_mb') or 0):,.0f} MB</td></tr>
<tr><td>Data folder</td><td class="small">{path_html(str(data_dir()))}</td></tr></table></div>
<p class="muted small">Every tool the prep runs also has <a href="/tools">its own page</a>.</p>
</div></div>
<script>(function(){{var d=new Set();
document.querySelectorAll('.set-cols form').forEach(function(f){{
f.addEventListener('input',function(){{d.add(f);f.classList.add('dirty')}});
f.addEventListener('submit',function(){{d.clear()}})}});window.addEventListener('beforeunload',function(ev){{
if(d.size){{ev.preventDefault();ev.returnValue=''}}}})}})()</script>"""
