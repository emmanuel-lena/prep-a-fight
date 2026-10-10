"""The week after (issue #22): when the app starts, it has already read your raid's last log and shows what to clean.

- For every character ticked "read my logs at launch" (setting `auto_logs`: "active", the default, follows the active
  character), the latest log of the character on Warcraft Logs (paf.tracker.character_report), no link to paste.
- A background process (`paf lastraid`, detached) reads it: the night pull by pull (paf.tracker, in the process),
  then per boss of the current raid in the log, as jobs of the app (their pages are the tools' pages): a boss killed,
  the character's rotation review (paf.rotation); a boss not killed, why (paf.wipe, needs the boss prepared) and the
  character's worst pull against their best (paf.pulldiff). The bosses not killed first.
- The state per character in <data>/web/lastraid.json; a log already read (same report, same number of pulls) is not
  read again.
- The home page opens on "Your last raid": per boss, two or three sentences from those results, the links to them.
The logs are read with the player's own key; nothing is sent anywhere.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from html import escape as e
from pathlib import Path

from paf.config import data_dir

FIGHTS = """query($c:String!){ reportData { report(code:$c) { startTime
  fights(killType: Encounters) { id encounterID difficulty kill bossPercentage } } } }"""
URL = "https://www.warcraftlogs.com/reports/{}"


def _path() -> Path:
    return data_dir() / "web" / "lastraid.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(state: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def ticked() -> set[str]:
    """The characters whose logs are read at launch."""
    from paf import characters, settings

    value = settings.get("auto_logs")
    if value == "active":
        cur = characters.current_slug()
        return {cur} if cur else set()
    return {s for s in value.split(",") if s}


def tick(slug: str, on: bool) -> None:
    from paf import settings

    now = ticked()
    now = now | {slug} if on else now - {slug}
    settings.set_value("auto_logs", ",".join(sorted(now)))


def who(slug: str) -> tuple[str, str, str]:
    """(name, server, region) of a character, from its /simc export."""
    from paf import characters

    p = characters._dir() / f"{slug}.simc"
    text = p.read_text(encoding="utf-8-sig") if p.is_file() else ""

    def field(key: str) -> str:
        m = re.search(rf'^{key}="?([^"\n]+)"?\s*$', text, re.M)
        return m.group(1).strip() if m else ""
    m = re.search(r'^(?:deathknight|demonhunter|druid|evoker|hunter|mage|monk|paladin|priest|rogue|shaman|warlock|'
                  r'warrior)="?([^"\n]+)"?', text, re.M)
    return (m.group(1).strip() if m else ""), field("server"), field("region")


def runner_alive(state: dict | None = None) -> bool:
    from paf.web import pid_alive

    state = load() if state is None else state
    return bool(state.get("_pid") and pid_alive(state["_pid"]))


def start() -> bool:
    """Start the reader in the background (unless it runs or no character is ticked)."""
    from paf.web import _env, _python

    if runner_alive() or not ticked():
        return False
    folder = data_dir() / "web"
    folder.mkdir(parents=True, exist_ok=True)
    flags = 0x00000008 | 0x08000000 if sys.platform == "win32" else 0  # DETACHED_PROCESS, CREATE_NO_WINDOW
    with (folder / "lastraid.log").open("a", encoding="utf-8") as out:
        subprocess.Popen([_python(), "-m", "paf", "lastraid"], stdout=out, stderr=subprocess.STDOUT,
                         creationflags=flags, env={**_env(), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                         **({} if sys.platform == "win32" else {"start_new_session": True}))
    return True


def again(slug: str) -> bool:
    """Read the character's last log again (the button)."""
    state = load()
    if slug in state:
        state[slug]["finished"] = None
        state[slug]["pulls"] = -1
        save(state)
    return start()


def bosses_of(fights: list[dict], encs) -> list[dict]:
    """The bosses of the current raid in a log, per difficulty: pulls, killed, the best pull's boss health left. Not
    killed first, then the raid's order."""
    from paf import settings

    names = {d: n for n, d in settings.DIFFICULTIES.items()}
    order = {x.id: i for i, x in enumerate(encs)}
    by: dict[tuple[int, int], dict] = {}
    for f in fights:
        if f.get("encounterID") not in order or f.get("difficulty") not in names or f["difficulty"] == 1:
            continue
        b = by.setdefault((f["encounterID"], f["difficulty"]), {
            "boss": f["encounterID"], "name": next(x.name for x in encs if x.id == f["encounterID"]),
            "difficulty": names[f["difficulty"]], "pulls": 0, "kill": False, "best": 100.0, "jobs": {}})
        b["pulls"] += 1
        b["kill"] = b["kill"] or bool(f.get("kill"))
        b["best"] = 0.0 if b["kill"] else min(b["best"], float(f.get("bossPercentage") or 100))
    return sorted(by.values(), key=lambda b: (b["kill"], order[b["boss"]]))


def _tools(b: dict, code: str, player: str) -> list[tuple[str, list[str]]]:
    base = [str(b["boss"]), "--difficulty", b["difficulty"], "--raid", URL.format(code)]
    if b["kill"]:
        return [("rotation", ["rotation", *base, "--player", player])]
    return [("wipe", ["wipe", *base]), ("diff", ["diff", *base, "--player", player])]


def read_one(client, slug: str, state: dict, encs, log=print) -> bool:
    """Read one character's last log into state[slug]; False when there is nothing new."""
    from paf import tracker
    from paf.jobrun import run_job

    name, server, region = who(slug)
    if not name or not server:
        return False
    code = tracker.character_report(client, name, server, region)
    if not code:
        return False
    rep = client.query(FIGHTS, {"c": code}, cache_ttl=120)["reportData"]["report"] or {}
    fights = rep.get("fights") or []
    old = state.get(slug) or {}
    if old.get("report") == code and old.get("pulls") == len(fights) and old.get("finished"):
        return False
    log(f"{name}: reading {code} ({len(fights)} pulls)")
    cur = {"report": code, "player": name, "date": (rep.get("startTime") or 0) / 1000, "pulls": len(fights),
           "night": None, "bosses": bosses_of(fights, encs), "started": time.time(), "finished": None}
    state[slug] = cur
    save(state)
    cur["night"], _outcome = run_job(["night", "--raid", URL.format(code)], log=log)
    save(state)
    for b in cur["bosses"]:
        for kind, args in _tools(b, code, name):
            jid, _outcome = run_job(args, log=log)
            b["jobs"][kind] = jid
            save(state)
    cur["finished"] = time.time()
    save(state)
    return True


def run(log=print) -> int:
    """The reader: every ticked character's last log."""
    from paf.wcl import WCLClient
    from paf.web import _encounters, journal_order

    state = load()
    if runner_alive(state) and state["_pid"] != os.getpid():
        return 0
    state["_pid"] = os.getpid()
    save(state)
    try:
        client = WCLClient()
        encs = journal_order(_encounters())
        for slug in sorted(ticked()):
            try:
                read_one(client, slug, state, encs, log)
            except Exception as ex:  # noqa: BLE001 - one character's log never stops the others
                log(f"{slug}: {ex}")
    finally:
        state["_pid"] = None
        save(state)
    return 0


# --- what the home page shows -------------------------------------------------------------------------------------

def _result(jid: str | None) -> dict | None:
    from paf import results
    from paf.jobrun import run_dir

    rd = run_dir(jid) if jid else None
    return results.read(rd) if rd else None


def _mmss(t: float) -> str:
    return "never" if t == float("inf") or t != t else f"{int(t // 60)}:{int(t % 60):02d}"


def sentences(b: dict, player: str) -> list[str]:
    """Two or three things to clean on a boss, from the results of its tools."""
    out: list[str] = []
    if b["kill"]:
        rot = _result(b["jobs"].get("rotation"))
        out += (rot or {}).get("highlights", [])
        return out
    w = _result(b["jobs"].get("wipe"))
    if w:
        kill = w.get("kill") or {}
        nd = kill.get("no_deaths", float("inf"))
        if nd != float("inf"):
            out.append(f"Your best pull left the boss at {w['left']:.0%}: without the deaths it dies at {_mmss(nd)} "
                       f"(the longest top kill: {_mmss(w['longest_kill'])}).")
        else:
            out.append(f"Your best pull left the boss at {w['left']:.0%}: even without the deaths, the damage is short.")
        me = next((c for c in w.get("culprits", []) if c["name"].lower() == player.lower()), None)
        if me and (me["lost_alive"] + me["lost_dead"]) >= 0.01:
            out.append(f"You: {me['lost_alive'] + me['lost_dead']:.1%} of the boss's health lost"
                       + (f", {me['lost_dead']:.1%} while dead" if me["lost_dead"] >= 0.005 else "")
                       + (f"; padding talents: {', '.join(me['pad_talents'])}" if me.get("pad_talents") else "") + ".")
    d = _result(b["jobs"].get("diff"))
    if d:
        out += [h["text"] for h in d.get("highlights", [])]
    return out


def _key(sentence: str) -> str:
    """What a sentence is about ("Halazzi's Rite", "Cleave (2-3 targets)"): the same point on several bosses."""
    return sentence.split(":", 1)[0].strip().lower()


def common(per_boss: list[list[str]]) -> list[str]:
    """The points that come back on most bosses (a talent, a buff never up): said once for the whole raid."""
    from collections import Counter

    if len(per_boss) < 3:
        return []
    count = Counter(k for says in per_boss for k in {_key(x) for x in says})
    keys = [k for k, n in count.most_common() if n >= max(3, len(per_boss) / 2)]
    out = []
    for k in keys[:3]:
        first = next(x for says in per_boss for x in says if _key(x) == k)
        out.append(first.replace(" on this boss", "").rstrip(".") + f" (on {count[k]} bosses).")
    return out


def card(slug: str) -> str:
    """'Your last raid' for the home page ('' when nothing was read for this character)."""
    from datetime import datetime

    state = load()
    cur = state.get(slug)
    reading = runner_alive(state)
    if not cur:
        if reading and slug in ticked():
            return ("<section class='lr' id='lastraid' data-reading='1'><h2>Your last raid</h2><p class='lr-wait'>"
                    "<span class='pl-spin'></span> Looking for your last log on Warcraft Logs&hellip;</p></section>")
        return ""
    total = sum(len(_tools(b, cur["report"], cur["player"])) for b in cur["bosses"])
    done = sum(len(b["jobs"]) for b in cur["bosses"])
    when = datetime.fromtimestamp(cur["date"]).strftime("%A %d %B") if cur.get("date") else ""
    night = f"<a href='/job/{e(cur['night'])}'>the night, pull by pull</a> &middot; " if cur.get("night") else ""
    head = (f"<h2>Your last raid</h2><p class='lr-sub'>{e(when)} &middot; {cur['pulls']} pulls &middot; {night}"
            f"<a href='{e(URL.format(cur['report']))}' target='_blank' rel='noopener'>the log</a></p>")
    if not cur["bosses"]:
        return f"<section class='lr' id='lastraid'>{head}<p>No boss of the current raid in this log.</p></section>"
    rows, folded = "", ""
    said = {b["boss"]: sentences(b, cur["player"]) for b in cur["bosses"]}
    raid_wide = common(list(said.values()))
    skip = {_key(x) for x in raid_wide}
    for b in cur["bosses"]:
        state_txt = (f"killed in {b['pulls']} {'pull' if b['pulls'] == 1 else 'pulls'}" if b["kill"] else
                     f"not killed: best pull at {b['best']:.0f}%, {b['pulls']} pulls")
        says = [x for x in said[b["boss"]] if _key(x) not in skip][:3]
        links = "".join(f"<a href='/job/{e(jid)}'>{label}</a>" for kind, label in
                        (("rotation", "Your rotation"), ("wipe", "Why it did not die"), ("diff", "Your best pull vs your worst"))
                        if (jid := b["jobs"].get(kind)))
        if not says and not cur["finished"]:
            body = "<p class='lr-wait'><span class='pl-spin'></span> Reading&hellip;</p>"
        else:
            body = ("<ul>" + "".join(f"<li>{e(s)}</li>" for s in says) + "</ul>") if says else \
                "<p class='muted small'>Nothing stands out.</p>"
        card_html = (f"<article class='lr-boss{' kill' if b['kill'] else ''}'><header><b>{e(b['name'])}</b>"
                 f"<span class='pill'>{e(b['difficulty'])}</span><span class='lr-state'>{state_txt}</span></header>"
                 f"{body}<nav class='lr-links'>{links}<a href='/boss?boss={b['boss']}&amp;difficulty={e(b['difficulty'])}'>"
                 f"The prep</a></nav></article>")
        if b["kill"]:
            folded += card_html
        else:
            rows += card_html
    killed = sum(b["kill"] for b in cur["bosses"])
    if folded:  # the bosses killed: one click away, the ones still to kill in view
        folded = (f"<details class='lr-more'><summary>The {killed} "
                  f"{'boss' if killed == 1 else 'bosses'} you killed</summary><div class='lr-grid'>{folded}</div></details>")
    progress = (f"<p class='lr-wait'><span class='pl-spin'></span> Reading your raid: {done} of {total} analyses"
                f"&hellip;</p>" if not cur["finished"] else "")
    again_btn = ("" if not cur["finished"] or reading else
                 "<form method='post' action='/lastraid/again' class='lr-again'><button class='btn ghost'>Read the "
                 "last log again</button></form>")
    wide = ("<div class='lr-wide'><b>On the whole raid</b><ul>" + "".join(f"<li>{e(x)}</li>" for x in raid_wide)
            + "</ul></div>") if raid_wide else ""
    return (f"<section class='lr' id='lastraid'{' data-reading=1' if not cur['finished'] else ''}>{head}{progress}"
            f"{wide}{f'<div class=lr-grid>{rows}</div>' if rows else ''}{folded}{again_btn}</section>")


CARD_JS = """<script>(function(){var s=document.getElementById('lastraid');if(!s||!s.dataset.reading)return;
setInterval(function(){fetch('/lastraid/card').then(function(r){return r.text()}).then(function(h){
var t=document.createElement('div');t.innerHTML=h;var n=t.firstElementChild;if(!n)return;s.replaceWith(n);s=n;
if(!n.dataset.reading)location.reload()}).catch(function(){})},10000)})();</script>"""
