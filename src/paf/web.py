"""Local web UI (`paf serve`): paste your /simc, pick a boss, tick your assignments, get the prep sheet.

Standard library only. Listens on 127.0.0.1. Long work (corpus, sims) runs as `paf` subprocesses whose
output is shown live; the result is the prep sheet page.
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from paf import settings, theme
from paf.config import data_dir, load_dotenv

e = html.escape


def bossguide_css() -> str:
    from paf.bossguide import CSS as GUIDE_CSS

    return GUIDE_CSS

CSS = theme.CSS + bossguide_css() + """
pre.log{max-height:460px;overflow:auto;background:var(--surface-2);border-radius:8px;padding:10px 12px}
.boss-tile .name{font-weight:700;font-size:16px;margin-bottom:6px}
.boss-tile .when{font-size:12px;color:var(--muted);margin-top:8px}
.boss-tile .top{font-size:13px;margin-top:10px;line-height:1.35}
.cta{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:18px 0 6px}
.lead{font-size:16px;color:var(--muted);margin-bottom:18px}
ol.steps{list-style:none;margin:0;padding:0} .st{padding:7px 0;border-bottom:1px solid var(--line)}
.st:last-child{border-bottom:0} .st span:first-child{display:inline-block;width:22px}
.st.done{color:var(--muted)} .st.done span:first-child{color:var(--pos)} .st.now{font-weight:700}
.st.now span:first-child{color:var(--accent)} .st.next{color:var(--muted)}
"""


def page(title: str, body: str, refresh: int | None = None, nav: str = "") -> bytes:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    nav = nav or ('<a href="/">Home</a><a href="/tools">Tools</a><a href="/settings">Settings</a>'
                  '<a href="/feedback">Feedback</a>')
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"{meta}<title>{e(title)}</title>{theme.HEAD}<style>{CSS}</style></head><body>{theme.topbar(nav)}"
            f"<main>{update_banner()}{body}</main></body></html>").encode()


QUIT = {"hook": None}  # set by the desktop app: closes its window (an update is being installed)


def update_banner() -> str:
    from paf import update

    rel = update.STATE.get("release")
    if rel is None:
        return ""
    action = ("<form method='post' action='/update' style='display:inline'><button class='btn'>Update now</button>"
              "</form>" if update.install_dir() else
              f"<a class='btn' href='{e(rel.url)}' target='_blank' rel='noopener'>Download it</a>")
    return (f"<div class='notice small row'><span><b>Version {e(rel.version)} is out</b> (you have "
            f"{e(update.__version__)}). <a href='{e(rel.url)}' target='_blank' rel='noopener'>What's new</a>"
            f"</span>{action}</div>")


def run_update() -> str:
    """Download the new installer, start it over this install and close the app (the installer reopens it)."""
    from paf import update

    rel, folder = update.STATE.get("release"), update.install_dir()
    if rel is None or folder is None:
        return "<h1>Nothing to update</h1><p><a href='/'>Back home</a></p>"
    if any(j.get("status") == "running" for j in JOBS.jobs.values()):
        return ("<h1>A prep is running</h1><p class='lead'>Updating would stop it. Update when it is done (the banner "
                "stays).</p><p><a href='/'>Back home</a></p>")
    try:
        setup = update.download(rel)
    except (OSError, ValueError) as ex:
        return (f"<h1>The update failed</h1><p class='notice'>{e(str(ex))}</p><p>Download it by hand: "
                f"<a href='{e(rel.url)}' target='_blank' rel='noopener'>{e(rel.url)}</a></p>")
    update.run_installer(setup, folder)
    threading.Timer(1.5, lambda: (QUIT["hook"] or (lambda: os._exit(0)))()).start()
    return (f"<h1>Updating to {e(rel.version)}&hellip;</h1><p class='lead'>The app closes now and reopens by itself "
            f"in a few seconds. Your preps and settings are kept.</p>")


class Jobs:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, args: list[str], result: Path | None) -> str:
        jid = uuid.uuid4().hex[:8]
        log = data_dir() / "web" / f"job-{jid}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        job = {"args": args, "log": log, "result": result, "status": "running", "started": time.time()}
        with self.lock:
            self.jobs[jid] = job
        self._save(jid, job)

        def run() -> None:
            with log.open("w", encoding="utf-8", errors="replace") as out:
                flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW
                proc = subprocess.run([_python(), "-m", "paf", *args], stdout=out, stderr=subprocess.STDOUT,
                                      env={**_env(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}, **flags)
            job["status"] = "done" if proc.returncode == 0 else f"failed (exit {proc.returncode})"
            self._save(jid, job)

        threading.Thread(target=run, daemon=True).start()
        return jid

    @staticmethod
    def _save(jid: str, job: dict) -> None:
        """Jobs are kept on disk: the progress page survives a restart of the app (the prep keeps running)."""
        import json

        meta = {"args": job["args"], "result": str(job["result"] or ""), "status": job["status"],
                "started": job["started"]}
        (data_dir() / "web" / f"job-{jid}.json").write_text(json.dumps(meta), encoding="utf-8")

    def get(self, jid: str) -> dict | None:
        import json
        import re

        if not re.fullmatch(r"[0-9a-f]{8}", jid):
            return None
        if jid in self.jobs:
            return self.jobs[jid]
        p = data_dir() / "web" / f"job-{jid}.json"
        if not p.is_file():
            return None
        meta = json.loads(p.read_text(encoding="utf-8"))
        log = data_dir() / "web" / f"job-{jid}.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        status = meta["status"]
        if status == "running":  # started by an earlier run of the app: read the outcome from the log
            status = "done" if "Prep sheet:" in text else "failed" if "Traceback" in text else (
                "running" if log.is_file() and time.time() - log.stat().st_mtime < 900 else "stopped")
        return {"args": meta["args"], "log": log, "result": Path(meta["result"]) if meta["result"] else None,
                "status": status, "started": meta["started"]}


def _python() -> str:
    """The console Python next to the running one (the desktop app runs under pythonw.exe)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").is_file():
        return str(exe.parent / "python.exe")
    return sys.executable


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


JOBS = Jobs()


def _profile_path() -> Path:
    return data_dir() / "profiles" / "current.simc"


def _encounters() -> list:
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    try:
        encs = raid_encounters(WCLClient())
    except Exception:  # noqa: BLE001 - the UI must still load without credentials
        return []
    zone = max((x.zone_id for x in encs), default=None)
    return [x for x in encs if x.zone_id == zone]


DIFF_NAMES = tuple(settings.DIFFICULTIES)


def split_key(key: str) -> tuple[str, str, str]:
    """'nek-zali-mythic-assassination-rogue' -> ('nek-zali', 'mythic', 'Assassination Rogue'). Reports made
    before the spec was part of the name have no spec."""
    import re

    m = re.match(rf"^(.+?)-({'|'.join(DIFF_NAMES)})(?:-(.+))?$", key)
    if not m:
        return key, "", ""
    return m.group(1), m.group(2), (m.group(3) or "").replace("-", " ").title()


def prepared() -> list[dict]:
    """Bosses with a prep sheet or a timeline in the reports folder, newest first."""
    import re

    reports = data_dir() / "reports"
    out: dict[str, dict] = {}
    for f in reports.glob("*.html") if reports.is_dir() else []:
        kind, _, key = f.stem.partition("-")
        if kind not in ("prep", "timeline") or not key:
            continue
        item = out.setdefault(key, {"key": key, "files": {}, "mtime": 0.0, "name": "", "difficulty": ""})
        item["files"][kind] = f.name
        item["mtime"] = max(item["mtime"], f.stat().st_mtime)
        if kind == "prep" and f.with_suffix(".json").is_file():
            import json

            try:
                item["headline"] = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
            except ValueError:
                pass
        boss, diff, spec = split_key(key)
        item.update(boss=boss, difficulty=diff, spec=spec)
        if not item["name"] or kind == "prep":
            m = re.search(rb"<title>(.*?)</title>", f.read_bytes()[:4000], re.S)
            title = html.unescape(m.group(1).decode("utf-8", "replace")) if m else key
            item["name"] = re.sub(r"\s+(prep|timelines)$", "", title).strip()
    return sorted(out.values(), key=lambda x: -x["mtime"])


def prepared_block() -> str:
    items = prepared()
    if not items:
        return ""
    tiles = "".join(
        f'<a class="tile boss-tile" href="/view/{e(x["key"])}"><div class="name">{e(x["name"])}</div>'
        f'<span class="pill gold">{e(x["difficulty"] or "?")}</span> '
        + (f'<span class="pill">{e(x["spec"])}</span> ' if x["spec"] else "")
        + f'<span class="pill">{"prep sheet + timelines" if len(x["files"]) == 2 else "prep sheet only" if "prep" in x["files"] else "timelines only"}</span>'
        + (f'<div class="top"><b class="pos">{x["headline"]["gain"]:+.1f}%</b> {e(x["headline"]["what"])}</div>'
           if x.get("headline", {}).get("gain") is not None else "")
        + f'<div class="when">updated {time.strftime("%d %b %H:%M", time.localtime(x["mtime"]))}</div></a>'
        for x in items)
    return f'<h2>Your prepared bosses</h2><div class="grid">{tiles}</div>'


TABS = (("prep", "Prep sheet"), ("timeline", "Top players' timelines"))


def view_page(key: str, tab: str) -> bytes:
    """One place per boss: the prep sheet and the top players' timelines as tabs (the reports stay standalone
    files, shown in a frame)."""
    item = next((x for x in prepared() if x["key"] == key), None)
    if item is None:
        return page("Not found", "<p>Nothing prepared for this boss yet.</p>")
    if tab not in item["files"]:
        tab = next(iter(k for k, _ in TABS if k in item["files"]))
    tabs = "".join(
        f'<a class="{"on" if k == tab else ""}" href="/view/{e(key)}?tab={k}">{e(label)}</a>'
        for k, label in TABS if k in item["files"])
    others = "".join(f'<option value="/view/{e(x["key"])}"{" selected" if x["key"] == key else ""}>'
                     f'{e(x["name"])} ({e(" ".join(filter(None, (x["difficulty"], x["spec"]))))})</option>'
                     for x in prepared())
    src = f'/report/{e(item["files"][tab])}'
    boss_link = _boss_link(item)
    nav = (f'<select onchange="location=this.value" aria-label="Boss">{others}</select>{tabs}'
           + (f'<a href="{e(boss_link)}">Edit &amp; re-run</a>' if boss_link else "")
           + f'<a href="{src}" target="_blank">Open alone</a>')
    css = "body{display:flex;flex-direction:column;height:100vh}iframe{border:0;width:100%;flex:1;display:block}"
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(item['name'])}</title>{theme.HEAD}<style>{CSS}{css}</style></head><body>{theme.topbar(nav)}"
            f'<iframe src="{src}" title="{e(item["name"])}"></iframe></body></html>').encode()


def _boss_link(item: dict) -> str:
    """The boss page of a prepared boss (assignments, raid, options), from its name."""
    try:
        from paf.corpus.template import _slug

        encs = _encounters()
    except Exception:  # noqa: BLE001 - the link is a convenience
        return ""
    enc = next((x for x in encs if item["boss"] == _slug(x.name)), None)
    return f"/boss?boss={enc.id}&difficulty={item['difficulty']}" if enc else ""


def has_credentials() -> bool:
    import os

    return bool(os.environ.get("WCL_CLIENT_ID") and os.environ.get("WCL_CLIENT_SECRET"))


def simc_block() -> str:
    """On first launch the app downloads SimulationCraft by itself: say so until it is there."""
    from paf.simc_install import simc_status

    state = simc_status()
    if not state:
        return ""
    if state == "downloading":
        return ('<p class="notice small"><b>First launch:</b> SimulationCraft (about 100 MB) is downloading in the '
                'background. You can connect to Warcraft Logs meanwhile; reload this page in a minute.</p>')
    return f'<p class="notice small">{e(state)} <a href="/tool/setup">Try again</a></p>'


def credentials_block(error: str = "") -> str:
    err = f'<p class="notice">{e(error)}</p>' if error else ""
    return f"""<div class="card step"><div class="num">0</div><div class="body">
<h3>Connect to Warcraft Logs <span class="pill">once</span></h3>
<p class="small">prep-a-fight reads the top players' logs with <b>your own</b> free Warcraft Logs API key (each player
has an hourly quota, so the key is not shared).</p>
<ol class="small">
<li>Log in on <a href="https://www.warcraftlogs.com/api/clients" target="_blank" rel="noopener">warcraftlogs.com/api/clients</a>
and click <b>Create Client</b>.</li>
<li>Name: anything (e.g. <code>prep-a-fight</code>). Redirect URL: <code>http://localhost</code>. Leave "Public Client"
unticked.</li>
<li>Copy the <b>Client ID</b> and the <b>Client Secret</b> here.</li></ol>{err}
<form method="post" action="/credentials" class="row"><input name="id" size="38" placeholder="Client ID" required>
<input name="secret" size="38" type="password" placeholder="Client Secret" required><button>Save and test</button></form>
<p class="tiny muted">Saved on this computer only, in {e(str(data_dir() / '.env'))}.</p></div></div>"""


def home(error: str = "") -> bytes:
    from paf.profile import parse_simc_export

    prof = _profile_path()
    loaded = None
    if prof.is_file():
        loaded = parse_simc_export(prof.read_text(encoding="utf-8-sig"))
    paste = """<form method="post" action="/profile"><textarea name="simc"
placeholder="In game: type /simc, then Ctrl+A, Ctrl+C, and paste here"></textarea>
<p><button>Load this character</button></p></form>"""
    if loaded is not None:
        from paf.profile import role

        warn = ("" if role(loaded) == "damage" else
                f'<p class="notice small">{e(loaded.spec.title())} is a {role(loaded)} spec: prep-a-fight only '
                f'prepares damage dealers for now (healers and tanks come later).</p>')
        character = (f"""<p><b>{e(loaded.name)}</b> <span class="pill gold">{e(loaded.spec)} {e(loaded.class_name)}</span>
<span class="pill">{len(loaded.candidates)} items in bags</span></p>{warn}
<details><summary>Load another character or an updated export</summary>{paste}</details>""")
    else:
        character = paste
    encs = _encounters()
    options = "".join(f'<option value="{x.id}">{e(x.name)}</option>' for x in encs)
    diff = settings.get("difficulty")
    diffs = "".join(f'<option{" selected" if d == diff else ""}>{d}</option>' for d in settings.DIFFICULTIES)
    boss_form = (f"""<form method="get" action="/boss" class="row">
<select name="boss" aria-label="Boss">{options}</select><select name="difficulty" aria-label="Difficulty">{diffs}</select>
<button>Continue</button></form>"""
                 if encs else '<p class="muted">Connect to Warcraft Logs first (step 0).</p>' if not has_credentials()
                 else '<p class="muted">Warcraft Logs did not answer: check your connection, then reload.</p>')
    creds = simc_block() + (credentials_block(error) if not has_credentials() or error else "")
    g, gs, gr = settings.get("guild"), settings.get("guild_server"), settings.get("guild_region")
    regions = "".join(f'<option{" selected" if r == gr else ""}>{r}</option>'
                      for r in settings.SETTINGS["guild_region"].choices)
    guild_state = f'<span class="pill gold">{e(g)}</span>' if g else '<span class="pill">optional</span>'
    guild = f"""<div class="card step"><div class="num">3</div><div class="body">
<h3>Your raid {guild_state}</h3>
<p class="small muted">Your guild's latest public log gives your raid's composition and DPS: the prep then tells you
whether the others cover the adds (stay on the boss) or you should pad them.</p>
<form method="post" action="/guild" class="row"><input name="guild" placeholder="Guild name" value="{e(g)}">
<input name="server" placeholder="Server" value="{e(gs)}"><select name="region" aria-label="Region">{regions}</select>
<button class="btn ghost">Save</button></form></div></div>"""
    body = f"""<h1>Prepare a boss fight</h1>
<p class="lead">The top players' logs, your character and SimulationCraft: your plan for this fight.</p>
{prepared_block()}
<h2>New prep</h2>{creds}
<div class="card step"><div class="num">1</div><div class="body"><h3>Your character</h3>{character}</div></div>
<div class="card step"><div class="num">2</div><div class="body"><h3>The boss</h3>{boss_form}</div></div>
{guild}"""
    return page("prep-a-fight", body)


def boss_page(boss_id: str, difficulty: str) -> bytes:
    from paf.assigns import load_mechanics
    from paf.corpus import db
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    enc = next((x for x in raid_encounters(WCLClient()) if str(x.id) == boss_id), None)
    if enc is None:
        return page("Unknown boss", "<p>Unknown boss.</p>")
    diff = settings.DIFFICULTIES.get(difficulty, 4)
    spec = settings.get("spec")
    con = db.connect()
    kills = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                        (enc.id, diff)).fetchone()[0]
    mechs = []
    if kills:
        try:
            mechs = load_mechanics(con, enc.id, diff, spec)
        except Exception:  # noqa: BLE001
            mechs = []
    current = {a.lower() for a in current_assigns(enc, difficulty)}
    if mechs:
        chips = ""
        for m in mechs:
            when = ", ".join(f"{int(t // 60)}:{int(t % 60):02d}" for t in m.times[:4]) + ("…" if len(m.times) > 4 else "")
            what = "interrupt" if m.kind == "interrupt" else f"{m.players_per_kill:.0f} players per kill"
            cost = f", ~{m.cost:g} s of movement" if m.cost else ""
            checked = " checked" if m.name.lower() in current or m.key in current else ""
            chips += (f'<label class="chip" title="{e(when)}"><input type="checkbox" name="assign" value="{e(m.name)}"'
                      f'{checked}>{e(m.name)} <span class="meta">{what}{cost}</span></label>')
        article = "an" if spec[:1].lower() in "aeiou" else "a"
        assigns = (f'<p class="small muted">Tick what you handle on this fight. Timings and the movement it costs '
                   f'{article} {e(spec)} come from the logs; hover a mechanic to see when it happens.</p>'
                   f'<div class="chips">{chips}</div>')
    elif kills:
        assigns = ('<p class="muted small">The mechanics are collected during the first prep (about 2 quota points '
                   'per kill); you can tick yours afterwards.</p>')
    else:
        assigns = ('<p class="muted small">No kill collected yet: the first prep collects ~200 ranked kills from '
                   'Warcraft Logs (a few minutes to an hour depending on your API quota).</p>')
    last = prepared_link(enc, difficulty)
    from paf import bossguide
    from paf.icons import icons_for

    sections = bossguide.load(enc.id, difficulty)
    guide = ""
    if sections:
        gicons = icons_for(bossguide.spell_refs(sections))
        guide = (f"<h2>The boss in 60 seconds</h2>{bossguide.summary_html(sections, 'damage')}"
                 f"<details class='card'><summary>Every ability, phase by phase (Encounter Journal)</summary>"
                 f"{bossguide.abilities_html(sections, mechanics=mechs, icon_map=gicons)}</details>"
                 f"<h2>Prepare it</h2>")
    body = f"""<p class="small"><a href="/">&larr; Home</a></p>
<h1>{e(enc.name)} <span class="pill gold">{e(difficulty)}</span></h1>
<p class="lead">{kills} ranked kills in your corpus.{last}</p>{guide}
<form method="post" action="/prep">
<input type="hidden" name="boss" value="{enc.id}"><input type="hidden" name="difficulty" value="{e(difficulty)}">
<div class="card step"><div class="num">1</div><div class="body"><h3>Your assignments</h3>{assigns}</div></div>
<div class="card step"><div class="num">2</div><div class="body"><h3>Your raid on this boss</h3>
<input name="raid" style="width:100%" value="{e(current_raid(enc, difficulty))}"
placeholder="Link to one of your raid's logs: https://www.warcraftlogs.com/reports/..." aria-label="Raid log link">
<p class="tiny muted" style="margin-top:6px">{e(raid_hint())}</p></div></div>
<div class="card step"><div class="num">3</div><div class="body"><h3>Your goal on this fight</h3>
<label><input type="radio" name="goal" value="auto" checked> Let the app decide <span class="muted small">(from
your raid's log; otherwise both plans are shown)</span></label>
<label><input type="radio" name="goal" value="boss"> Boss damage first <span class="muted small">(your raid lead
wants you on the boss)</span></label>
<label><input type="radio" name="goal" value="total"> Total damage <span class="muted small">(pad the adds)</span>
</label></div></div>
<div class="card step"><div class="num">4</div><div class="body"><h3>What to sim</h3>
<label><input type="checkbox" name="gear" checked> Best gear from your bags, and what this boss drops for you</label>
<label><input type="checkbox" name="optimize" checked> Ideal cooldown plan per objective
<span class="muted small">(the slowest part: 20 to 40 min)</span></label></div></div>
<div class="cta"><button class="btn big">Prepare this fight</button>
<span class="small muted">Runs on your computer; you can follow it live.</span></div></form>
<h2>Advanced</h2>
<details class="card"><summary>Your fight plan: your own movements, Bloodlust, Power Infusion</summary>
{plan_block(enc, difficulty)}</details>
<details class="card"><summary>What you know about this boss: damage amps, targets to ignore</summary>
{notes_block(enc, difficulty)}</details>"""
    return page(enc.name, body)


def prepared_link(enc, difficulty: str) -> str:
    from paf.corpus.template import report_key

    key = report_key(enc.name, difficulty)
    return f' <a href="/view/{e(key)}">Open the last prep sheet &rarr;</a>' if any(
        x["key"] == key for x in prepared()) else ""


def _plan_path(enc, difficulty: str) -> Path:
    from paf.corpus.template import template_path

    return template_path(enc.name, difficulty).with_suffix(".plan.txt")


def current_raid(enc, difficulty: str) -> str:
    from paf.plan import parse_plan

    p = _plan_path(enc, difficulty)
    try:
        return parse_plan(p.read_text(encoding="utf-8-sig")).raid if p.is_file() else ""
    except ValueError:
        return ""


def raid_hint() -> str:
    g = settings.get("guild")
    if g:
        return (f"Empty: the latest public log of {g} is used. Your raid's composition and DPS decide whether you pad "
                f"the adds or stay on the boss.")
    return ("Optional. Your raid's composition and DPS decide whether you pad the adds or stay on the boss. "
            "Or set your guild once on the home page.")


def write_raid(boss_id: int, difficulty: str, url: str) -> None:
    """Keep the raid log link as the `raid` line of the boss plan file."""
    from paf.corpus.template import template_path
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    enc = next((x for x in raid_encounters(WCLClient()) if x.id == boss_id), None)
    if enc is None:
        return
    p = template_path(enc.name, difficulty).with_suffix(".plan.txt")
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8-sig").splitlines() if p.is_file() else []
    lines = [line for line in lines if not line.strip().lower().startswith("raid ")]
    if url.strip():
        lines.append(f"raid {url.strip()}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def current_assigns(enc, difficulty: str) -> list[str]:
    from paf.plan import parse_plan

    p = _plan_path(enc, difficulty)
    if not p.is_file():
        return []
    try:
        return parse_plan(p.read_text(encoding="utf-8-sig")).assigns
    except ValueError:
        return []


def plan_block(enc, difficulty: str) -> str:
    """The player's own fight plan (moves, lust, PI), editable; assignments are the ticked mechanics above."""
    from paf.corpus.template import template_path
    from paf.fight import Fight
    from paf.plan import plan_template

    p = _plan_path(enc, difficulty)
    if p.is_file():
        text = p.read_text(encoding="utf-8-sig")
    elif template_path(enc.name, difficulty).is_file():
        text = plan_template(Fight.load(template_path(enc.name, difficulty)))
    else:
        return ('<p class="muted small">Available after the first prep: your own movements (a soak at 2:45, a '
                "dodge...), Bloodlust and Power Infusion timings, on top of the rebuilt fight.</p>")
    return f"""<p class="small muted">What you do on this fight that the logs cannot guess, one line each: <code>2:45 move 6</code>
(6 s of movement), <code>5:30 move 8 shift -5..+5</code> (the optimizer picks the best moment), <code>lust 0:00</code>,
<code>pi 0:20 2:30</code>, <code>no boss-movement</code>. The mechanics ticked above are added as <code>assign</code> lines.
Every sim of the prep (gear, talents, cooldowns) runs on this fight.</p>
<form method="post" action="/plan"><input type="hidden" name="boss" value="{enc.id}">
<input type="hidden" name="difficulty" value="{e(difficulty)}"><textarea name="plan">{e(text)}</textarea>
<p><button class="btn ghost">Save the plan</button></p></form>"""


def notes_block(enc, difficulty: str) -> str:
    """What the player knows about the boss: the detected mechanics with their evidence, editable."""
    from paf.corpus.template import template_path
    from paf.notes import notes_path

    p = notes_path(template_path(enc.name, difficulty))
    if not p.is_file():
        return ('<p class="muted small">Available after the first prep: the detected mechanics (units sharing the '
                "boss's health, damage amps...) with their evidence.</p>")
    text = p.read_text(encoding="utf-8-sig")
    return f"""<p class="small muted">Detected in the logs, with the evidence. Correct what the logs cannot tell (e.g. the
real damage amp of a heart: <code>amp Venomous Heart 2.0</code>), save, then prepare the fight again.</p>
<form method="post" action="/notes"><input type="hidden" name="boss" value="{enc.id}">
<input type="hidden" name="difficulty" value="{e(difficulty)}"><textarea name="notes">{e(text)}</textarea>
<p><button class="btn ghost">Save the notes</button></p></form>"""


def write_assigns(boss_id: int, difficulty: str, chosen: list[str]) -> None:
    """Write the ticked assignments as uncommented `assign` lines in the boss plan file."""
    from paf.corpus.template import template_path
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    enc = next((x for x in raid_encounters(WCLClient()) if x.id == boss_id), None)
    if enc is None:
        return
    ppath = template_path(enc.name, difficulty).with_suffix(".plan.txt")
    ppath.parent.mkdir(parents=True, exist_ok=True)
    lines = ppath.read_text(encoding="utf-8-sig").splitlines() if ppath.is_file() else []
    lines = [line for line in lines if not line.strip().lower().startswith("assign ")]
    lines += [f"assign {c}" for c in chosen]
    ppath.write_text("\n".join(lines) + "\n", encoding="utf-8")


# the steps of a prep, as `paf prep` prints them, with their typical duration in minutes on a first run
PREP_STEPS = (
    ("Using the prep pack", "Load what the top players' logs give, already computed (prep pack)", 0),
    ("Collecting the corpus", "Download the top players' kills from Warcraft Logs", 20),
    ("Collecting who handles", "Who handles each mechanic", 4),
    ("Analyzing the corpus", "Rebuild the typical fight", 2),
    ("Calibrating the fight", "Calibrate it on the logs", 1),
    ("Validating the fight", "Check it against the top players' real DPS", 2),
    ("Your raid and the adds", "Your raid and the adds", 1),
    ("Simming your character", "Sim your character", 1),
    ("Cooldown timelines", "Top players' cooldown timelines", 1),
    ("Talent builds", "Sim the top players' talent builds", 3),
    ("Ideal cooldown plan", "Find your best cooldown plan", 20),
    ("Cooldown plans", "Compare cooldown plans", 5),
    ("Top Gear", "Best gear from your bags", 5),
    ("What this boss drops", "What this boss drops for you", 3),
)


def prep_progress(log: str) -> tuple[list[tuple[str, str]], float]:
    """[(label, state)] with state done / now / next, and the typical minutes left. Steps that a prep
    skips (the corpus already collected, no raid set...) are not listed."""
    seen = [line[3:] for line in log.splitlines() if line.startswith("== ")]
    finished = any(s.startswith("Done") for s in seen)
    idx = {i for i, (prefix, _, _) in enumerate(PREP_STEPS) for s in seen if s.startswith(prefix)}
    last = max(idx) if idx else -1
    rows, left = [], 0.0
    optional = ("Collecting", "Your raid", "Cooldown plans", "Using the prep pack")
    if any(s.startswith("Using the prep pack") for s in seen):  # the pack replaces the corpus and the validation
        optional += ("Analyzing", "Validating")
    for i, (prefix, label, minutes) in enumerate(PREP_STEPS):
        if i in idx:
            rows.append((label, "done" if finished or i < last else "now"))
        elif not finished and i > last and not prefix.startswith(optional):
            rows.append((label, "next"))
            left += minutes
    if last >= 0 and not finished:
        left += PREP_STEPS[last][2] / 2
    return rows, left


def feedback_page(jid: str = "", note: str = "") -> str:
    from paf import feedback

    what, log = feedback.job_log(jid) if jid else ("", feedback.app_log())
    _, preview = feedback.report("(your message)", what, log)
    dest = ("sent to the prep-a-fight team" if feedback.endpoint() else
            "opened as a GitHub issue in your browser, for you to post (a free GitHub account is needed)")
    return f'''<h1>Send feedback</h1>{note}<p class="lead">A bug, a wrong number, an idea: it is {dest}.</p>
<form method="post" action="/feedback" class="card"><input type="hidden" name="job" value="{e(jid)}">
<label>Your message <textarea name="message" required placeholder="What you did, what you expected, what you got.
Your spec and the boss help."></textarea></label>
<label class="chip"><input type="checkbox" name="log" checked> Attach the {"log of this prep" if jid else "app's log"}
(below; your Warcraft Logs key, user folder and email addresses are removed)</label>
<div class="cta"><button class="btn">Send</button></div></form>
<details class="card"><summary>Exactly what is sent</summary><pre class="log">{e(preview[-20000:])}</pre></details>'''


def send_feedback(form: dict) -> str:
    from paf import feedback

    jid = (form.get("job") or [""])[0]
    message = (form.get("message") or [""])[0]
    what, log = feedback.job_log(jid) if jid else ("", feedback.app_log())
    title, body = feedback.report(message, what, log if form.get("log") else "")
    url = feedback.endpoint()
    if url:
        try:
            link = feedback.send(url, title, body)
            track = (f" You can follow it here: <a href='{e(link)}' target='_blank' rel='noopener'>{e(link)}</a>."
                     if link else "")
            return f"<h1>Thanks!</h1><p class='lead'>Your feedback was sent.{track} <a href='/'>Back home</a></p>"
        except (OSError, ValueError) as ex:
            note = f"<p class='notice small'>Sending failed ({e(str(ex))}): post it on GitHub instead.</p>"
    else:
        note = ""
    return (f"<h1>Almost done</h1>{note}<p class='lead'>Your report is ready on GitHub: open it, check it, and click "
            f"<b>Create</b>.</p><div class='cta'><a class='btn big' target='_blank' rel='noopener' "
            f"href='{e(feedback.issue_url(title, body))}'>Open the GitHub issue</a></div>")


def job_page(jid: str) -> bytes:
    job = JOBS.get(jid)
    if job is None:
        return page("Unknown job", "<p>This prep is unknown (its files were removed?). <a href='/'>Home</a></p>")
    log = job["log"].read_text(encoding="utf-8", errors="replace") if job["log"].is_file() else ""
    elapsed = int(time.time() - job["started"])
    if job["status"] == "done" and job["result"] and job["result"].is_file():
        key = job["result"].stem.partition("-")[2]
        go = f"/view/{e(key)}"
        return (page("Done", f'<h1>Your prep is ready</h1><p class="lead">Opening the prep sheet&hellip;</p>'
                             f'<div class="cta"><a class="btn big" href="{go}">Open the prep sheet</a></div>'
                             f'<details class="card"><summary>What was done (log)</summary><pre class="log">'
                             f'{e(log[-20000:])}</pre></details>')
                .replace(b"<head>", f'<head><meta http-equiv="refresh" content="2;url={go}">'.encode(), 1))
    status = job["status"]
    if job["args"] and job["args"][0] != "prep":  # a tool: its output, then the reports it wrote
        from paf.webtools import new_reports

        name = job["args"][0]
        if status == "running":
            return page(name, f"<h1>Running: {e(name)}</h1><p class='lead'><span id='el' "
                              f"data-start='{job['started']:.0f}'>{elapsed // 60} min {elapsed % 60:02d} s</span>. "
                              f"This page updates itself.</p><div class='card'><pre class='log'>{e(log[-8000:])}"
                              f"</pre></div>", 5)
        links = "".join(f"<li><a href='/report/{e(r)}'>{e(r)}</a></li>" for r in new_reports(job["started"]))
        head = "Finished" if status == "done" else f"Stopped ({e(status)})"
        return page(name, f"<h1>{head}: {e(name)}</h1>"
                          + (f"<h2>Reports written</h2><div class='card'><ul>{links}</ul></div>" if links else "")
                          + f"<h2>Output</h2><div class='card'><pre class='log'>{e(log[-20000:])}</pre></div>"
                          + f"<p><a class='btn ghost' href='/tool/{e(name)}'>Run it again</a></p>")
    if status == "done":
        return page("Done", "<h1>The prep finished</h1><p class='lead'>Its sheet is listed on the "
                            "<a href='/'>home page</a>.</p>")
    rows, left = prep_progress(log)
    icon = {"done": "&#10003;", "now": "&#9679;", "next": "&#9675;"}
    items = "".join(f"<li class='st {state}'><span>{icon[state]}</span> {e(label)}"
                    + (" <span class='pill gold'>in progress</span>" if state == "now" else "") + "</li>"
                    for label, state in rows)
    if status == "running":
        head = "Preparing the fight"
        eta = (f"about {max(1, round(left))} min left (typical first prep; much faster when the logs and sims "
               f"are already cached)" if left else "almost done")
        lead = (f"<span id='el' data-start='{job['started']:.0f}'>{elapsed // 60} min {elapsed % 60:02d} s</span>"
                f" &middot; {eta}. You can leave this page open, it updates itself; the prep keeps running on your "
                f"computer even if you close it.")
    else:
        head = "The prep stopped" if status == "stopped" else f"The prep failed ({e(status)})"
        lead = ("The log below says why. Go back to the boss page to try again, or "
                f"<a class='btn' href='/feedback?job={e(jid)}'>Send this report</a> (you see it before it goes).")
    js = """<script>(function(){var el=document.getElementById('el');if(!el)return;var s=+el.dataset.start;
setInterval(function(){var t=Math.max(0,Math.floor(Date.now()/1000-s));el.textContent=Math.floor(t/60)+' min '+
String(t%60).padStart(2,'0')+' s'},1000)})();</script>"""
    body = (f"<h1>{head}</h1><p class='lead'>{lead}</p><div class='card'><ol class='steps'>{items}</ol></div>"
            f"<details class='card'><summary>Details (log)</summary><pre class='log'>{e(log[-6000:])}</pre></details>"
            + js)
    return page("Preparing...", body, 10 if status == "running" else None)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:  # quiet
        pass

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":
                self._send(home())
            elif url.path == "/boss":
                self._send(boss_page(q.get("boss", ""), q.get("difficulty", settings.get("difficulty"))))
            elif url.path == "/tools":
                from paf.webtools import tools_page

                self._send(page("Tools", tools_page()))
            elif url.path.startswith("/tool/"):
                from paf.webtools import tool_page

                body = tool_page(url.path.rsplit("/", 1)[1], _encounters())
                self._send(page("Tool", body) if body else page("Not found", "<p>Unknown tool.</p>"),
                           200 if body else 404)
            elif url.path == "/settings":
                from paf.webtools import settings_page

                self._send(page("Settings", settings_page()))
            elif url.path == "/feedback":
                self._send(page("Feedback", feedback_page(q.get("job", ""))))
            elif url.path.startswith("/view/"):
                self._send(view_page(url.path.rsplit("/", 1)[1], q.get("tab", "prep")))
            elif url.path.startswith("/job/"):
                self._send(job_page(url.path.rsplit("/", 1)[1]))
            elif url.path.startswith("/report/"):
                name = Path(url.path).name
                f = data_dir() / "reports" / name
                if f.is_file() and f.suffix in (".html", ".txt"):
                    ctype = "text/html; charset=utf-8" if f.suffix == ".html" else "text/plain; charset=utf-8"
                    body = f.read_bytes()
                    if f.suffix == ".html":  # links between reports (timeline) go through /report/
                        body = body.replace(b'href="timeline-', b'href="/report/timeline-')
                    self._send(body, ctype=ctype)
                else:
                    self._send(page("Not found", "<p>Not found.</p>"), 404)
            else:
                self._send(page("Not found", "<p>Not found.</p>"), 404)
        except Exception as ex:  # noqa: BLE001 - show the error in the page instead of dropping the connection
            self._send(page("Error", f"<h1>Error</h1><pre>{e(repr(ex))}</pre>"), 500)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
        try:
            if self.path == "/profile":
                from paf.profile import looks_like_export

                text = (form.get("simc") or [""])[0]
                if not looks_like_export(text):
                    self._send(page("Not a /simc export", "<p>That does not look like a /simc export. "
                                                          "<a href='/'>Back</a></p>"), 400)
                    return
                p = _profile_path()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
                from paf.profile import parse_simc_export, use_profile_spec

                use_profile_spec(parse_simc_export(text))
                self._redirect("/")
            elif self.path == "/notes":
                from paf.corpus.template import template_path
                from paf.encounters import raid_encounters
                from paf.notes import notes_path, parse_notes
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                text = (form.get("notes") or [""])[0].replace("\r\n", "\n")
                try:
                    parse_notes(text)
                except ValueError as ex:
                    self._send(page("Invalid notes", f"<p>{e(str(ex))}. <a href='javascript:history.back()'>Back</a></p>"), 400)
                    return
                enc = next(x for x in raid_encounters(WCLClient()) if x.id == boss_id)
                notes_path(template_path(enc.name, difficulty)).write_text(text, encoding="utf-8")
                self._redirect(f"/boss?boss={boss_id}&difficulty={difficulty}")
            elif self.path.startswith("/tool/"):
                from paf.webtools import tool_args

                args = tool_args(self.path.rsplit("/", 1)[1], form)
                if args is None or args[0] in ("serve", "profile", "config"):
                    self._send(page("Not found", "<p>Unknown tool.</p>"), 404)
                    return
                self._redirect(f"/job/{JOBS.start(args, None)}")
            elif self.path == "/feedback":
                self._send(page("Feedback", send_feedback(form)))
            elif self.path == "/update":
                self._send(page("Update", run_update()))
            elif self.path == "/update/check":
                from paf import update

                rel = update.check_now()
                self._send(page("Updates", f"<h1>Updates</h1><p class='lead'>Version {e(rel.version)} is out: see the "
                                           f"banner above.</p>" if rel else
                                f"<h1>Updates</h1><p class='lead'>You have the latest version "
                                f"({e(update.__version__)}).</p><p><a href='/settings'>Back to Settings</a></p>"))
            elif self.path == "/settings":
                from paf.webtools import settings_page

                errors = []
                for key in settings.SETTINGS:
                    if key in form:
                        try:
                            settings.set_value(key, form[key][0])
                        except (KeyError, ValueError) as ex:
                            errors.append(f"{key}: {ex}")
                self._send(page("Settings", settings_page("; ".join(errors) if errors else "Saved.")))
            elif self.path == "/guild":
                settings.set_value("guild", (form.get("guild") or [""])[0])
                settings.set_value("guild_server", (form.get("server") or [""])[0])
                settings.set_value("guild_region", (form.get("region") or ["eu"])[0])
                self._redirect("/")
            elif self.path == "/credentials":
                from paf.config import save_credentials
                from paf.wcl import WCLClient, WCLError
                from paf.webtools import settings_page

                cid, secret = (form.get("id") or [""])[0].strip(), (form.get("secret") or [""])[0].strip()
                from_settings = (form.get("back") or [""])[0] == "settings"
                try:
                    WCLClient(cid, secret).rate_limit()
                except (WCLError, OSError) as ex:
                    error = f"Warcraft Logs refused these credentials (the old key is kept): {ex}"
                    self._send(page("Settings", settings_page(error)) if from_settings else home(error), 400)
                    return
                save_credentials(cid, secret)
                if from_settings:
                    self._send(page("Settings", settings_page("New Warcraft Logs key saved and tested.")))
                else:
                    self._redirect("/")
            elif self.path == "/plan":
                from paf.encounters import raid_encounters
                from paf.plan import parse_plan
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                text = (form.get("plan") or [""])[0].replace("\r\n", "\n")
                try:
                    parse_plan(text)
                except ValueError as ex:
                    self._send(page("Invalid plan", f"<p>{e(str(ex))}. <a href='javascript:history.back()'>Back</a></p>"), 400)
                    return
                enc = next(x for x in raid_encounters(WCLClient()) if x.id == boss_id)
                p = _plan_path(enc, difficulty)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
                self._redirect(f"/boss?boss={boss_id}&difficulty={difficulty}")
            elif self.path == "/prep":
                from paf.corpus.template import report_key
                from paf.encounters import raid_encounters
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                write_assigns(boss_id, difficulty, form.get("assign", []))
                raid = (form.get("raid") or [""])[0]
                if raid.strip():
                    from paf.raidneed import report_code

                    try:
                        report_code(raid)
                    except ValueError as ex:
                        self._send(page("Invalid log link", f"<p>{e(str(ex))}. "
                                                            f"<a href='javascript:history.back()'>Back</a></p>"), 400)
                        return
                write_raid(boss_id, difficulty, raid)
                enc = next(x for x in raid_encounters(WCLClient()) if x.id == boss_id)
                args = ["prep", str(boss_id), "--difficulty", difficulty]
                if "gear" not in form:
                    args.append("--no-gear")
                if "optimize" not in form:
                    args.append("--no-optimize")
                goal = (form.get("goal") or ["auto"])[0]
                if goal in ("boss", "total"):
                    args += ["--objective", goal]
                result = data_dir() / "reports" / f"prep-{report_key(enc.name, difficulty)}.html"
                jid = JOBS.start(args, result)
                self._redirect(f"/job/{jid}")
            else:
                self._send(page("Not found", "<p>Not found.</p>"), 404)
        except Exception as ex:  # noqa: BLE001
            self._send(page("Error", f"<h1>Error</h1><pre>{e(repr(ex))}</pre>"), 500)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        """A browser closing or resetting a connection (tab closed, prefetch, reload...) is normal: no traceback."""
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    load_dotenv()
    server = Server(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"prep-a-fight is running on {url} (Ctrl+C to stop)")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
