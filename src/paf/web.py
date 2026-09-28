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
<p class="muted">Top players' logs, your character, SimulationCraft: the plan for this fight.</p>
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
</div><p><button>Prepare this fight</button></p></form>"""
    return page(enc.name, body)


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
        return page("Done", f'<h1>Done</h1><p><a class="btn" href="/report/{e(job["result"].name)}">Open the prep sheet</a>'
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
