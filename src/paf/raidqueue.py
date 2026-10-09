"""Prepare the whole raid in one press (issue #21): press once, go cook, come back to every boss prepared.

- The queue: every boss of the raid for the active character at one difficulty, in the Encounter Journal's order;
  a boss already prepared this week is skipped. It lives in <data>/web/raidqueue.json.
- A runner process (`paf raidqueue`, detached: closing the window does not stop it) prepares the bosses one after
  the other, each as an ordinary prep of the app (its job file: the raid board and the banners show its progress).
  First pass: the first sheet of every boss (FIRST_SHEET kills, or a pack). Second pass, once every boss has its
  sheet: the full analysis of the bosses whose corpus has more kills to download (`prep --refine`). One prep at a
  time: they share the Warcraft Logs quota and the CPU.
- While it runs, an icon in the notification area (paf.tray): its tooltip says where it is, a notification says
  when the first boss and when the whole raid are ready, a click opens the app, its menu stops the queue.
- Switching to another character pauses the queue (its preps are the queued character's); preparing again resumes.
- After the weekly reset, the app starts the queue again by itself for the bosses it had prepared (setting
  `refresh_after_reset`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from paf.config import data_dir

TITLE = "prep-a-fight"  # the app window's title (paf.desktop.TITLE), to bring it to the front


def _path() -> Path:
    return data_dir() / "web" / "raidqueue.json"


def load() -> dict | None:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(q: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(q, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def build(encs, difficulty: str, character: str, ready: set[int]) -> dict:
    """A new queue: every boss of `encs` (already in the Journal's order), the ones in `ready` (prepared this week)
    skipped."""
    items = [{"boss": x.id, "name": x.name, "pass": "first", "status": "ready" if x.id in ready else "waiting"}
             for x in encs]
    return {"created": time.time(), "difficulty": difficulty, "character": character, "items": items,
            "stop": False, "paused": "", "pid": None, "notified": [], "finished": None}


def runner_alive(q: dict | None) -> bool:
    from paf.web import pid_alive

    return bool(q and q.get("pid") and pid_alive(q["pid"]))


def active(q: dict | None) -> bool:
    """Whether the queue is still working (its runner alive and something left to do)."""
    return runner_alive(q) and any(i["status"] in ("waiting", "running") for i in q["items"])


def progress(q: dict) -> tuple[int, int, dict | None]:
    """(first sheets ready, bosses in the queue, the item running now)."""
    first = [i for i in q["items"] if i["pass"] == "first"]
    ready = sum(i["status"] in ("ready", "done") for i in first)
    running = next((i for i in q["items"] if i["status"] == "running"), None)
    return ready, len(first), running


def waiting(q: dict | None, difficulty: str) -> set[int]:
    """The bosses still to prepare in the queue at this difficulty (the raid board shows them as queued)."""
    if not q or q.get("difficulty") != difficulty or not runner_alive(q):
        return set()
    return {i["boss"] for i in q["items"] if i["pass"] == "first" and i["status"] == "waiting"}


def start(q: dict) -> bool:
    """Save the queue and start its runner. False while another queue runs (stop it first)."""
    if runner_alive(load()):
        return False
    save(q)
    spawn_runner()
    return True


def _keep(q: dict) -> None:
    """The runner saves its queue without losing a stop asked meanwhile (by the app or the icon's menu)."""
    now = load()
    if now and now.get("stop"):
        q["stop"] = True
    save(q)


def spawn_runner() -> None:
    from paf.web import _env, _python

    folder = data_dir() / "web"
    folder.mkdir(parents=True, exist_ok=True)
    flags = 0x00000008 | 0x08000000 if sys.platform == "win32" else 0  # DETACHED_PROCESS, CREATE_NO_WINDOW
    with (folder / "raidqueue.log").open("a", encoding="utf-8") as out:
        subprocess.Popen([_python(), "-m", "paf", "raidqueue"], stdout=out, stderr=subprocess.STDOUT,
                         creationflags=flags, env={**_env(), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                         **({} if sys.platform == "win32" else {"start_new_session": True}))


def stop() -> None:
    """Stop the queue: the prep running now is stopped too (it starts again from scratch if the queue resumes)."""
    q = load()
    if q:
        q["stop"] = True
        save(q)


# --- the estimate --------------------------------------------------------------------------------------------------

@dataclass
class RaidEstimate:
    minutes: float  # until every boss has its first sheet
    bosses: int
    collect: int  # bosses whose kills download from Warcraft Logs
    packs: int  # bosses from a prep pack
    wait: float = 0.0  # minutes waiting for the quota


def estimate(con, encs, difficulty: int, class_name: str, spec: str, client=None) -> RaidEstimate:
    """paf.estimate for every boss, the Warcraft Logs quota shared: the downloads add up within one key's hour."""
    from paf import estimate as est

    plans = [est.plan(con, x.id, difficulty, class_name, spec) for x in encs]
    points = sum(p.kills * (est.POINTS_PER_KILL + est.MECH_POINTS_PER_KILL) for p in plans)
    left, reset = est.QUOTA, 60.0
    if client is not None and points:
        try:
            rl = client.rate_limit()
            left, reset = max(0.0, rl["limitPerHour"] - rl["pointsSpentThisHour"]), rl["pointsResetIn"] / 60
        except Exception:  # noqa: BLE001 - unknown quota: a fresh hour
            pass
    wait = 0.0
    if points > left:
        wait = reset + 60.0 * max(0.0, (points - left) / est.QUOTA - 1)
    minutes = sum(p.minutes - p.wait for p in plans) + wait
    return RaidEstimate(minutes, len(plans), sum(p.source == "collect" for p in plans),
                        sum(p.source.startswith("pack") for p in plans), wait)


# --- the runner ----------------------------------------------------------------------------------------------------

def _open_app() -> None:
    from paf.tray import bring_to_front

    if bring_to_front(TITLE):
        return
    exe = Path(sys.executable)
    gui = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").is_file() else exe
    flags = 0x00000008 if sys.platform == "win32" else 0
    subprocess.Popen([str(gui), "-m", "paf.desktop"], creationflags=flags, close_fds=True)


def _pending(boss: int, difficulty: str) -> int:
    from paf import settings
    from paf.corpus import db

    con = db.connect()
    return con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='pending'",
                       (boss, settings.DIFFICULTIES.get(difficulty, 4))).fetchone()[0]


def _run_item(q: dict, item: dict, log=print) -> str:
    """Run one prep as a job of the app; 'done', 'failed' or 'stopped' (the queue was stopped meanwhile)."""
    from paf.corpus.template import report_key
    from paf.jobrun import run_job

    args = ["prep", str(item["boss"]), "--difficulty", q["difficulty"], "--queued"]
    if item["pass"] == "full":
        args.append("--refine")
    result = data_dir() / "reports" / f"prep-{report_key(item['name'], q['difficulty'])}.html"

    def started(jid: str) -> None:
        item["job"] = jid
        _keep(q)

    _jid, outcome = run_job(args, result, lambda: bool((load() or {}).get("stop")), started, log)
    return outcome


def _next(q: dict) -> dict | None:
    """The next item to run; once every first sheet is made, the full analyses of the bosses with kills left."""
    for i in q["items"]:
        if i["status"] == "waiting" and i["pass"] == "first":
            return i
    if not any(i["pass"] == "full" for i in q["items"]):
        for i in [i for i in q["items"] if i["pass"] == "first" and i["status"] == "done"]:
            if _pending(i["boss"], q["difficulty"]):
                q["items"].append({"boss": i["boss"], "name": i["name"], "pass": "full", "status": "waiting"})
    return next((i for i in q["items"] if i["status"] == "waiting"), None)


def run(log=print) -> int:
    """The runner: prepares the queue's bosses one after the other, until done, stopped or paused."""
    from paf import characters
    from paf.tray import Tray

    q = load()
    if not q or (runner_alive(q) and q["pid"] != os.getpid()):
        return 0
    q.update(pid=os.getpid(), stop=False, paused="")
    for i in q["items"]:  # a runner that died mid-prep: that boss is redone
        if i["status"] == "running":
            i["status"] = "waiting"
    save(q)
    tray = Tray("prep-a-fight: preparing your raid", str(Path(__file__).parent / "assets" / "prep-a-fight.ico"),
                [("Open prep-a-fight", _open_app), ("Stop preparing", stop)], _open_app)
    try:
        while True:
            q["stop"] = (load() or q).get("stop", False)
            if q["stop"]:
                break
            if characters.current_slug() != q["character"]:
                q["paused"] = "character"
                tray.notify("Your raid prep is paused", "You switched to another character. Prepare the raid "
                                                        "again on it to go on.")
                break
            item = _next(q)
            if item is None:
                break
            ready, total, _ = progress(q)
            what = "Full analysis of" if item["pass"] == "full" else "Preparing"
            tray.set_tip(f"prep-a-fight: {what} {item['name']} ({ready}/{total} ready)")
            item["status"] = "running"
            _keep(q)
            outcome = _run_item(q, item, log)
            item["status"] = "waiting" if outcome == "stopped" else outcome
            _keep(q)
            if outcome == "stopped":
                q["stop"] = True
                break
            ready, total, _ = progress(q)
            if item["pass"] == "first" and outcome == "done" and "first" not in q["notified"]:
                q["notified"].append("first")
                tray.notify(f"{item['name']} is ready", f"Your prep sheet is waiting. {total - ready} more to go."
                            if total > ready else "Your prep sheet is waiting.")
            if ready == total and "all" not in q["notified"] and not any(
                    i["status"] == "waiting" and i["pass"] == "first" for i in q["items"]):
                q["notified"].append("all")
                failed = sum(i["status"] == "failed" for i in q["items"] if i["pass"] == "first")
                word = "boss" if total == 1 else "bosses"
                tray.notify("Your raid is ready", f"{total} {word} prepared. Open prep-a-fight to read them."
                            if not failed else f"{total - failed} of {total} {word} prepared.")
            _keep(q)
    finally:
        q["pid"] = None
        if not any(i["status"] == "waiting" for i in q["items"]) and not q.get("stop"):
            q["finished"] = time.time()
        _keep(q)
        time.sleep(1)  # the last notification shows before the icon goes
        tray.close()
    return 0


def after_reset(encs) -> bool:
    """At the app's start: the week turned since the last queue of this character ended, the bosses it prepared
    are prepared again (setting `refresh_after_reset`). True when a queue started."""
    from datetime import UTC, datetime

    from paf import characters, pack, settings

    q = load()
    if settings.get("refresh_after_reset") != "on" or not q or runner_alive(q) or not q.get("finished"):
        return False
    if q["character"] != characters.current_slug():
        return False
    if not pack.is_stale(datetime.fromtimestamp(q["created"], UTC).isoformat()):
        return False
    before = {i["boss"] for i in q["items"] if i["pass"] == "first"}
    todo = [x for x in encs if x.id in before]
    if not todo:
        return False
    from paf.web import fresh_bosses

    ready = fresh_bosses(todo, q["difficulty"], settings.get("class"), settings.get("spec"))
    return start(build(todo, q["difficulty"], q["character"], ready))
