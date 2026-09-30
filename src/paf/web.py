"""Local web UI (`paf serve`): paste your /simc, pick a boss, tick your assignments, get the prep sheet.

Standard library only. Listens on 127.0.0.1. Long work (corpus, sims) runs as `paf` subprocesses whose
output is shown live; the result is the prep sheet page.
"""

from __future__ import annotations

import html
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from paf import settings
from paf.config import data_dir, load_dotenv

e = html.escape

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--line:#e6e3dc;--card:#fff;--acc:#1c64d6;--acc-fg:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#ececf0;--muted:#9a9aa3;--line:#2a2a31;--card:#1d1d22;
--acc:#6ea8ff;--acc-fg:#0b1020}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:20px 16px}
main{max-width:860px;margin:auto} h1{font-size:24px;margin:0 0 4px} h2{font-size:17px;margin:24px 0 8px}
.muted{color:var(--muted)} .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
textarea{width:100%;min-height:180px;font:12px ui-monospace,monospace;box-sizing:border-box;background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-radius:6px;padding:8px}
select,input,button{font:inherit} button,.btn{background:var(--acc);color:var(--acc-fg);border:0;border-radius:6px;padding:8px 14px;
cursor:pointer;text-decoration:none;display:inline-block} label{display:block;margin:4px 0}
table{border-collapse:collapse;width:100%} td,th{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;color:var(--muted)} pre{white-space:pre-wrap;font:12px ui-monospace,monospace;max-height:420px;overflow:auto}
.small{font-size:12px} .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
"""


def page(title: str, body: str, refresh: int | None = None) -> bytes:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"{meta}<title>{e(title)}</title><style>{CSS}</style></head><body><main>"
            f'<p class="small"><a href="/">prep-a-fight</a></p>{body}</main></body></html>').encode()


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

        def run() -> None:
            with log.open("w", encoding="utf-8", errors="replace") as out:
                proc = subprocess.run([sys.executable, "-m", "paf", *args], stdout=out, stderr=subprocess.STDOUT,
                                      env={**_env(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
            job["status"] = "done" if proc.returncode == 0 else f"failed (exit {proc.returncode})"

        threading.Thread(target=run, daemon=True).start()
        return jid


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
        diff = next((d for d in DIFF_NAMES if key.endswith("-" + d)), "")
        item["difficulty"] = diff
        if not item["name"] or kind == "prep":
            m = re.search(rb"<title>(.*?)</title>", f.read_bytes()[:4000], re.S)
            title = html.unescape(m.group(1).decode("utf-8", "replace")) if m else key
            item["name"] = re.sub(r"\s+(prep|timelines)$", "", title).strip()
    return sorted(out.values(), key=lambda x: -x["mtime"])


def prepared_block() -> str:
    items = prepared()
    if not items:
        return ""
    rows = "".join(
        f'<tr><td><a href="/view/{e(x["key"])}"><b>{e(x["name"])}</b></a></td><td>{e(x["difficulty"])}</td>'
        f'<td class="small muted">{"prep sheet + timelines" if len(x["files"]) == 2 else ", ".join(x["files"])}'
        f'</td><td class="small muted">{time.strftime("%Y-%m-%d %H:%M", time.localtime(x["mtime"]))}</td></tr>'
        for x in items)
    return f'<h2>Your prepared bosses</h2><div class="card"><table>{rows}</table></div>'


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
        (f'<b class="tab on">{e(label)}</b>' if k == tab else
         f'<a class="tab" href="/view/{e(key)}?tab={k}">{e(label)}</a>') if k in item["files"] else
        f'<span class="tab muted">{e(label)}</span>'
        for k, label in TABS)
    others = "".join(f'<option value="/view/{e(x["key"])}"{" selected" if x["key"] == key else ""}>'
                     f'{e(x["name"])} ({e(x["difficulty"])})</option>' for x in prepared())
    src = f'/report/{e(item["files"][tab])}'
    body = f"""<div class="bar"><a href="/"><b>prep-a-fight</b></a>
<select onchange="location=this.value">{others}</select>
<nav>{tabs}</nav><a class="small" href="{src}" target="_blank">open alone</a></div>
<iframe src="{src}" title="{e(item['name'])}"></iframe>"""
    css = """body{padding:0;margin:0}.bar{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:8px 16px;
border-bottom:1px solid var(--line);background:var(--card)}.bar a{color:inherit}nav{display:flex;gap:4px}
.tab{padding:6px 12px;border-radius:6px;text-decoration:none}.tab.on{background:var(--acc);color:var(--acc-fg)}
a.tab:hover{background:var(--line)}iframe{border:0;width:100%;height:calc(100vh - 52px);display:block}"""
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(item['name'])}</title><style>{CSS}{css}</style></head><body>{body}</body></html>").encode()


def home() -> bytes:
    from paf.profile import parse_simc_export

    prof = _profile_path()
    status = "No character loaded yet."
    if prof.is_file():
        p = parse_simc_export(prof.read_text(encoding="utf-8-sig"))
        status = f"Current character: <b>{e(p.name)}</b> ({e(p.spec)} {e(p.class_name)}), {len(p.candidates)} items in bags."
    encs = _encounters()
    options = "".join(f'<option value="{x.id}">{e(x.name)}</option>' for x in encs)
    diff = settings.get("difficulty")
    diffs = "".join(f'<option{" selected" if d == diff else ""}>{d}</option>' for d in settings.DIFFICULTIES)
    boss_form = (f"""<form method="get" action="/boss" class="row">
<select name="boss">{options}</select><select name="difficulty">{diffs}</select><button>Next</button></form>"""
                 if encs else '<p class="muted">Warcraft Logs credentials missing: run <code>paf doctor</code>.</p>')
    body = f"""<h1>Prepare a boss fight</h1>
<p class="muted">Top players' logs, your character, SimulationCraft: the plan for this fight.</p>{prepared_block()}
<h2>1. Your character</h2><div class="card"><p>{status}</p>
<form method="post" action="/profile"><textarea name="simc" placeholder="In game: /simc, Ctrl+A, Ctrl+C, paste here"></textarea>
<p><button>Load this character</button></p></form></div>
<h2>2. The boss</h2><div class="card">{boss_form}</div>"""
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
    if mechs:
        rows = ""
        for m in mechs:
            when = ", ".join(f"{int(t // 60)}:{int(t % 60):02d}" for t in m.times[:6])
            what = "kick" if m.kind == "interrupt" else f"{m.players_per_kill:.0f} players / kill"
            rows += (f'<tr><td><label><input type="checkbox" name="assign" value="{e(m.name)}"> {e(m.name)}</label></td>'
                     f"<td>{what}</td><td>{m.cost:g}s moving</td><td class='small'>{when}</td></tr>")
        assigns = f"""<table><tr><th>Mechanic</th><th>Who</th><th>Cost for {e(spec)}</th><th>When</th></tr>{rows}</table>"""
    elif kills:
        assigns = ('<p class="muted">Mechanics are not collected yet for this boss: they will be during the prep '
                   '(about 2 quota points per kill).</p>')
    else:
        assigns = ('<p class="muted">No kill collected yet: the prep starts by collecting ~200 ranked kills from '
                   'Warcraft Logs (a few minutes to an hour depending on your API quota).</p>')
    body = f"""<h1>{e(enc.name)} <span class="muted">({e(difficulty)})</span></h1>
<p class="muted">{kills} kills in your corpus.</p>
<form method="post" action="/prep">
<input type="hidden" name="boss" value="{enc.id}"><input type="hidden" name="difficulty" value="{e(difficulty)}">
<h2>3. Your assignments</h2><div class="card">{assigns}</div>
<h2>4. Options</h2><div class="card">
<label><input type="checkbox" name="gear" checked> Top Gear with your bags and this boss's loot (slower)</label>
<label><input type="checkbox" name="optimize" checked> Ideal cooldown plan per objective (slowest, 20-40 min)</label>
</div><p><button>Prepare this fight</button></p></form>{notes_block(enc, difficulty)}"""
    return page(enc.name, body)


def notes_block(enc, difficulty: str) -> str:
    """What the player knows about the boss: the detected mechanics with their evidence, editable."""
    from paf.corpus.template import template_path
    from paf.notes import notes_path

    p = notes_path(template_path(enc.name, difficulty))
    if not p.is_file():
        return ('<h2>What you know about this boss</h2><div class="card muted">Available after the first prep: '
                "the detected mechanics (units sharing the boss's health, damage amps...) with their evidence.</div>")
    text = p.read_text(encoding="utf-8-sig")
    return f"""<h2>What you know about this boss</h2><div class="card">
<p class="small muted">Detected in the logs, with the evidence. Correct what the logs cannot tell (e.g. the real damage
amp of a heart: <code>amp Venomous Heart 2.0</code>), save, then prepare the fight again.</p>
<form method="post" action="/notes"><input type="hidden" name="boss" value="{enc.id}">
<input type="hidden" name="difficulty" value="{e(difficulty)}"><textarea name="notes">{e(text)}</textarea>
<p><button>Save the notes</button></p></form></div>"""


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


def job_page(jid: str) -> bytes:
    job = JOBS.jobs.get(jid)
    if job is None:
        return page("Unknown job", "<p>Unknown job.</p>")
    log = job["log"].read_text(encoding="utf-8", errors="replace") if job["log"].is_file() else ""
    elapsed = int(time.time() - job["started"])
    if job["status"] == "done" and job["result"] and job["result"].is_file():
        key = job["result"].stem.partition("-")[2]
        return page("Done", f'<h1>Done</h1><p><a class="btn" href="/view/{e(key)}">Open the prep sheet</a>'
                            f'</p><details><summary>Log</summary><pre>{e(log[-20000:])}</pre></details>')
    status = job["status"]
    refresh = 5 if status == "running" else None
    return page("Working...", f"<h1>{'Working' if status == 'running' else e(status)}</h1>"
                              f"<p class='muted'>{elapsed // 60} min {elapsed % 60:02d} s. This page refreshes itself.</p>"
                              f"<div class='card'><pre>{e(log[-6000:])}</pre></div>", refresh)


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
            elif self.path == "/prep":
                from paf.corpus.template import _slug
                from paf.encounters import raid_encounters
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                write_assigns(boss_id, difficulty, form.get("assign", []))
                enc = next(x for x in raid_encounters(WCLClient()) if x.id == boss_id)
                args = ["prep", str(boss_id), "--difficulty", difficulty]
                if "gear" not in form:
                    args.append("--no-gear")
                if "optimize" not in form:
                    args.append("--no-optimize")
                result = data_dir() / "reports" / f"prep-{_slug(enc.name)}-{difficulty}.html"
                jid = JOBS.start(args, result)
                self._redirect(f"/job/{jid}")
            else:
                self._send(page("Not found", "<p>Not found.</p>"), 404)
        except Exception as ex:  # noqa: BLE001
            self._send(page("Error", f"<h1>Error</h1><pre>{e(repr(ex))}</pre>"), 500)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    load_dotenv()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
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
