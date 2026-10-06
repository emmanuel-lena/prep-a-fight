"""Every `paf` command in the app: a form per command, built from its command-line options (nothing to keep
in sync by hand), run as a job like the prep; and the settings / status page."""

from __future__ import annotations

import argparse
import html
import os
import time

from paf import settings
from paf.config import data_dir

e = html.escape

GROUPS = (
    ("Prepare a boss", ("prep", "raid", "raidplan", "timeline", "mechanics", "assigns")),
    ("Sims on the fight", ("topgear", "droptimizer", "talents", "optimize", "cdplan", "plan", "sim")),
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


def tools_page() -> str:
    cmds = subparsers()
    out = ["<h1>Tools</h1><p class='lead'>Every command of prep-a-fight, with its options. The prep (on a boss "
           "page) runs most of them for you; use these to redo one part, or to dig further.</p>"]
    for title, names in GROUPS:
        tiles = "".join(f'<a class="tile" href="/tool/{n}"><b>{e(n)}</b><div class="small muted">{e(_help(n))}</div>'
                        f"</a>" for n in names if n in cmds)
        out.append(f"<h2>{e(title)}</h2><div class='grid'>{tiles}</div>")
    return "".join(out)


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
    fields = "".join(_field(a, encounters) for a in sp._actions if a.dest not in SKIP_OPTIONS)  # noqa: SLF001
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


def settings_page(message: str = "") -> str:
    from paf.cache import cache_root, size
    from paf.simc_install import find_simc

    rows = ""
    for key, s in settings.SETTINGS.items():
        cur = settings.get(key)
        if s.choices:
            ctrl = f"<select name='{e(key)}'>" + "".join(
                f"<option{' selected' if c == cur else ''}>{e(c)}</option>" for c in s.choices) + "</select>"
        else:
            ctrl = f"<input name='{e(key)}' value='{e(str(cur))}'>"
        rows += f"<tr><td><b>{e(key)}</b><div class='tiny muted'>{e(s.help)}</div></td><td>{ctrl}</td></tr>"
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
    msg = f"<p class='notice small'>{e(message)}</p>" if message else ""
    cid = os.environ.get("WCL_CLIENT_ID", "")
    current = (f"Current key: client <code>{e(cid[:8])}…</code>" if cid else
               "<span class='neg'>No key yet.</span>")
    return f"""<h1>Settings</h1>{msg}
<form method="post" action="/settings" class="card"><table>{rows}</table>
<div class="cta"><button class="btn">Save</button></div></form>
<h2>Warcraft Logs key</h2><div class="card"><p class="small">{current} To use another one (a new client, or a
regenerated secret): create or open it on <a href="https://www.warcraftlogs.com/api/clients" target="_blank"
rel="noopener">warcraftlogs.com/api/clients</a>, then paste both values.
It is tested before it replaces the old one.</p>
<form method="post" action="/credentials" class="row"><input type="hidden" name="back" value="settings">
<input name="id" size="38" placeholder="Client ID" required>
<input name="secret" size="38" type="password" placeholder="Client Secret" required autocomplete="off">
<button>Save and test</button></form>
<p class="tiny muted">Saved on this computer only, in {e(str(data_dir() / '.env'))}.</p></div>
<h2>Status</h2><div class="card"><table>
<tr><td>SimulationCraft</td><td class="small">{simc}
<form method="post" action="/tool/setup" style="display:inline">
<button class="btn ghost">Update</button></form></td></tr>
<tr><td>Warcraft Logs</td><td class="small">{quota}</td></tr>
<tr><td>Caches (sims, logs)</td><td class="small">{size(cache_root()) / 1e6:,.0f} MB
(cap {settings.get('cache_max_mb')} MB)</td></tr>
<tr><td>Data folder</td><td class="small">{e(str(data_dir()))}</td></tr>
<tr><td>Checked</td><td class="small">{time.strftime('%d %b %H:%M')}</td></tr></table></div>"""
