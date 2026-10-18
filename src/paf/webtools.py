"""Every `paf` command in the app: a form per command, built from its command-line options (nothing to keep
in sync by hand), run as a job like the prep; and the settings / status page."""

from __future__ import annotations

import argparse
import html
import os

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
        ("difficulty", "Difficulty", "The difficulty a new prep starts on."),
        ("guild", "Guild", "Its latest log gives your raid's composition (who hits the adds, pad or not)."),
        ("guild_server", "Guild's server", "For example Kazzak."),
        ("guild_region", "Guild's region", ""),
    ]),
    ("The app", False, [
        ("refresh_after_reset", "Prepare again after the weekly reset",
         "After the weekly reset, the app prepares again by itself the bosses you prepared last week with "
         "\"Prepare the whole raid\"."),
        ("share_packs", "Share the prep packs you compute",
         "Fight data only, no names: the next player of your spec skips the log download."),
        ("check_updates", "Look for new versions", "Every 10 minutes, on GitHub."),
    ]),
    ("Advanced: the logs read, the quota, the caches", True, [
        ("corpus_size", "Kills read per boss", "The top kills a prep reads, then keeps reading in the background."),
        ("corpus_points", "Quota for background reading",
         "Warcraft Logs points per hour (of 3600) the reading in the background may use; a prep you wait for "
         "uses the whole quota."),
        ("region", "Rankings from one region only", "All regions unless you pick one."),
        ("cache_max_mb", "Disk cache cap (MB)", "Sim results and Warcraft Logs answers; the oldest go first."),
        ("onboarded", "First-run steps done", "Off: the welcome steps show again."),
    ]),
]


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
    return f"<input name='{e(key)}' id='s-{e(key)}' value='{e(str(cur))}'{kind}>"


def settings_form() -> str:
    """The settings, grouped and in words, with one Save."""
    # set elsewhere, never typed: the class and spec follow the active character, the last raids read are ticked
    # per character in Characters
    listed = {k for _g, _f, rows in SETTINGS_FORM for k, _l, _h in rows}
    listed |= {"class", "spec", "auto_logs", "language"}  # set elsewhere; the language: English only before 1.0
    groups = [(g, folded, [r for r in rows if r[0] in settings.SETTINGS]) for g, folded, rows in SETTINGS_FORM]
    groups[-1][2].extend((k, k.replace("_", " ").capitalize(), s.help) for k, s in settings.SETTINGS.items()
                         if k not in listed)
    out = ""
    for group, folded, rows in groups:
        fields = "".join(
            f"<div class='set-row{' set-check' if settings.SETTINGS[k].choices == ('on', 'off') else ''}'>"
            f"<label for='s-{e(k)}'>{e(label)}</label>{_setting_control(k)}"
            f"{f'<p class=set-help>{e(help_)}</p>' if help_ else ''}</div>" for k, label, help_ in rows)
        out += (f"<details class='set-group' open><summary>{e(group)}</summary>{fields}</details>" if folded else
                f"<fieldset class='set-group'><legend>{e(group)}</legend>{fields}</fieldset>")
    return out


def settings_page(message: str = "") -> str:
    from paf.cache import cache_root, size
    from paf.simc_install import find_simc

    exe = find_simc(None)
    simc = e(str(exe)) if exe else "<span class='neg'>not installed</span>"
    quota = ""
    try:
        from paf.wcl import WCLClient

        rl = WCLClient().rate_limit()
        quota = (f"{rl['pointsSpentThisHour']:.0f} / {rl['limitPerHour']} points used this hour "
                 f"(reset in {int(rl['pointsResetIn']) // 60} min)")
    except Exception as ex:  # noqa: BLE001 - shown as is
        quota = f"<span class='neg'>{e(str(ex)[:160])}</span>"
    msg = f"<p class='notice small' role='status'>{e(message)}</p>" if message else ""
    from paf import wcllogin
    from paf.web import connect_block

    cid = os.environ.get("WCL_CLIENT_ID", "")
    current = (f"Current key: client <code>{e(cid[:8])}…</code>" if cid else
               "Not used: the app goes through your Warcraft Logs login." if wcllogin.logged_in() else
               "<span class='neg'>No key yet.</span>")
    if wcllogin.logged_in():
        account = ("<p class='small'>Connected with your Warcraft Logs account.</p><form method='post' "
                   "action='/wcl/logout'><button class='btn ghost'>Disconnect</button></form>")
    elif cid:  # the key works already: connecting is an option, not the page's action
        account = ("<p class='small'>The app reads the logs with your own API key (below). You can connect with "
                   "your Warcraft Logs account instead: one login in your browser, no key to keep.</p>"
                   + connect_block(lead=False, ghost=True))
    else:
        account = connect_block(lead=False)
    account = (f"<h2>Warcraft Logs</h2><div class='card'>{account}</div>" if wcllogin.available() else "")
    return f"""<h1>Settings</h1><p class="lead">Your raid, the app, your Warcraft Logs access and where things stand.
</p>{msg}<div class="set-cols"><div>
<form method="post" action="/settings" class="card settings">{settings_form()}
<div class="cta"><button class="btn go">Save</button></div></form></div><div>
{account}<h2>Warcraft Logs key</h2><div class="card"><p class="small measure">{current} To use another one (a new
client, or a regenerated secret): create or open it on <a href="https://www.warcraftlogs.com/api/clients"
target="_blank" rel="noopener">warcraftlogs.com/api/clients</a>, then paste both values.
It is tested before it replaces the old one.</p>
<form method="post" action="/credentials" class="row"><input type="hidden" name="back" value="settings">
<input name="id" class="key-in" placeholder="Client ID" aria-label="Client ID" required>
<input name="secret" class="key-in" type="password" placeholder="Client Secret" aria-label="Client Secret" required
autocomplete="off">
<button class="btn ghost">Save and test</button></form>
<p class="tiny muted">Saved on this computer only, in {e(str(data_dir() / '.env'))}.</p></div>
<h2>Status</h2><div class="card"><table class="status">
<tr><td>SimulationCraft</td><td class="small"><div class="val"><span>{simc}</span>
<form method="post" action="/tool/setup">
<button class="btn ghost">Update</button></form></div></td></tr>
<tr><td>prep-a-fight</td><td class="small"><div class="val"><span>version {e(__version__)}</span>
<form method="post" action="/update/check"><button class="btn ghost">Check for updates</button></form></div></td></tr>
<tr><td>Warcraft Logs</td><td class="small">{quota}</td></tr>
<tr><td>Caches (sims, logs)</td><td class="small">{size(cache_root()) / 1e6:,.0f} MB
(cap {settings.get('cache_max_mb')} MB)</td></tr>
<tr><td>Data folder</td><td class="small">{e(str(data_dir()))}</td></tr></table></div>
<h2>Every tool</h2><div class="card"><p class="small">The prep of a boss runs them all; each one is also on its own
page, to dig further.</p><p><a class="btn ghost" href="/tools">See every tool &rarr;</a></p></div>
</div></div>"""
