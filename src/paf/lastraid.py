"""The week after (issue #22): when the app starts, it has already read your raid's last log and shows what to clean.

- For every character ticked "read my logs at launch" (setting `auto_logs`: "active", the default, follows the active
  character), the character's latest log with a boss of the current raid (paf.tracker.character_reports), no
  link to paste.
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
from paf.theme import diff_pill

FIGHTS = """query($c:String!){ reportData { report(code:$c) { startTime
  fights(killType: Encounters) { id encounterID difficulty kill bossPercentage startTime endTime } } } }"""
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
        if f.get("kill") and f.get("endTime") and not b["kill"]:  # how long the raid takes (issue #26)
            b["kill_time"] = round((f["endTime"] - f.get("startTime", 0)) / 1000, 1)
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
    code, rep, fights = None, {}, []
    for c in tracker.character_reports(client, name, server, region):  # the latest log with a boss of the raid
        r = client.query(FIGHTS, {"c": c}, cache_ttl=120)["reportData"]["report"] or {}
        if bosses_of(r.get("fights") or [], encs):
            code, rep, fights = c, r, r.get("fights") or []
            break
    if not code:
        return False
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


def _failed(jid: str | None) -> bool:
    try:
        return bool(jid) and not json.loads((data_dir() / "web" / f"job-{jid}.json").read_text(
            encoding="utf-8")).get("status", "").startswith(("done", "running"))
    except (OSError, ValueError):
        return False


def _pulls(n: int) -> str:
    return f"{n} pull{'s' if n != 1 else ''}"


def _mmss(t: float) -> str:
    return "never" if t == float("inf") or t != t else f"{int(t // 60)}:{int(t % 60):02d}"


def sentences(b: dict, player: str) -> list[str]:
    """Two or three things to clean on a boss, from the results of its tools."""
    out: list[str] = []
    if b["kill"]:
        rot = _result(b["jobs"].get("rotation")) or {}
        if rot.get("findings"):  # priced first (issue #24): what it costs, what the top players do, where in the log
            for f in rot["findings"][:3]:
                noise = f.get("noise")
                cost = ((f"up to &minus;{f['cost']:.1f}%" if f.get("approx") else f"&minus;{f['cost']:.1f}%")
                        + ("" if f.get("approx") or noise is None else
                           f" <small>&plusmn;{noise:.1f}</small>" if noise >= 0.1 else " <small>&plusmn;&lt;0.1</small>")
                        if f.get("cost") is not None else "")
                out.append({"text": f["text"], "cost": cost, "tops": f.get("tops", ""), "link": f.get("link", ""),
                            "at": f.get("at"), "value": f.get("cost"), "kind": f.get("kind", ""),
                            "approx": bool(f.get("approx")),
                            "name": f.get("name", "")})
            return out
        out += rot.get("highlights", [])
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
    if d:  # B is the better pull of the two (paf.pulldiff.player_pair, default_pair)
        for h in d.get("highlights", []):  # a row of the pulls' table (the owner: less text)
            row = h.get("row") or _row_of(h["text"])  # a result read before the rows: from its sentence
            out.append({"cmp": [_you(row[0], player), *row[1:]], "kind": h.get("kind", ""),
                        "pulls": [_pull_label(d.get("b")), _pull_label(d.get("a"))],
                        "text": _ab(h["text"], player)} if row else _ab(h["text"], player))
    return out


def _ab(text: str, player: str = "") -> str:
    """A pull comparison's sentence for the page, where "A" and "B" mean nothing and the player is "you"."""
    text = re.sub(r"\bin B\b", "in your best pull", text)
    text = re.sub(r"\bin A\b", "in your weaker pull", text)
    if player and text.lower().startswith(player.lower() + ":"):
        text = "You:" + text[len(player) + 1:]
    return text


def _you(label: str, player: str) -> str:
    """"Ixuu: damage on the boss" -> "You: damage on the boss"."""
    return "You:" + label[len(player) + 1:] if player and label.lower().startswith(player.lower() + ":") else label


ROWS = ((r"^(.+): (\S+) on the boss in B, (\S+) in A\.$", "{0}: boss DPS"),
        (r"^(.+): active (\S+) of the pull in B, (\S+) in A\.$", "{0}: time casting"),
        (r"^At (\d+:\d\d), the boss had (\S+) left in B against (\S+) in A\.$", "Boss health left at {0}"),
        (r"^Deaths before the wipe: (\S+) in B, (\S+) in A\.$", "Deaths before the wipe"),
        (r"^Share of the raid's damage on (.+): (\S+) in B, (\S+) in A\.$", "Raid damage on {0}"),
        (r"^(.+): died (\d+) time\(s\) in B, (\d+) in A\.$", "{0}: deaths"))


def _pull_label(side: dict | None) -> str:
    """"pull 27, 2:38": a compared pull, as the log names it, with its length."""
    if not side:
        return ""
    label, dur = side.get("label") or "", side.get("duration")  # the label names its length already
    return label if label or not dur else _mmss(dur)


def _row_of(text: str) -> list[str] | None:
    """A pull comparison's sentence (paf.pulldiff) as a table row: what, its value in B, in A."""
    for pat, label in ROWS:
        m = re.match(pat, text)
        if m:
            g = m.groups()
            return [label.format(*g[:-2]), g[-2], g[-1]] if len(g) == 3 else [label, g[0], g[1]]
    return None


def _delta(b: str, a: str) -> str:
    """The best pull against the weaker one, in % when both are numbers ("252k", "209k" -> "+21%")."""
    def num(x: str) -> float | None:
        m = re.fullmatch(r"([\d.,]+)(k|%)?", x)
        return float(m[1].replace(",", "")) if m else None
    x, y = num(b), num(a)
    if x is None or y is None:
        return ""
    if b.endswith("%"):
        return f"{x - y:+.0f} pts"
    return f"{(x - y) / y:+.0%}" if y else ""


def _signed_word(gap: str, kind: str | None) -> str:
    """A gap that is good while its sign is minus (less boss health left): said in words, never "-3 pts" in the
    gain colour (DESIGN: a sign always says the same thing)."""
    if gap.startswith("-") and kind == "good":
        return gap[1:] + " lower"
    if gap.startswith("+") and kind == "bad":
        return gap[1:] + " higher"
    return gap


def _cmp_table(rows: list[dict]) -> str:
    """The best pull against the weaker one, a measure a row, the better value marked (good or bad for you)."""
    if not rows:
        return ""
    lab = rows[0].get("pulls") or ["", ""]  # which pulls: "Pull 27 (2:38)", so an expert can check them
    # the comparison's own pulls: its best and worst without a death (paf.pulldiff), not the night's best pull
    return ("<table class='lr-cmp fit'><thead><tr><th>No-death pulls</th>"
            f"<th>Better{' <small>' + e(lab[0]) + '</small>' if lab[0] else ''}</th>"
            f"<th>Weaker{' <small>' + e(lab[1]) + '</small>' if lab[1] else ''}</th><th>Gap</th></tr>"
            "</thead><tbody>"
            + "".join(f"<tr class='{e(r.get('kind', ''))}'><td>{e(r['cmp'][0])}</td><td><b>{e(r['cmp'][1])}</b></td>"
                      f"<td>{e(r['cmp'][2])}</td><td class='gap'>{e(_signed_word(_delta(r['cmp'][1], r['cmp'][2]), r.get('kind')))}"
                      f"{' &#10007;' if r.get('kind') == 'bad' else ''}</td>"  # a mark where it goes the wrong way only
                      "</tr>" for r in rows) + "</tbody></table>")


def _key(sentence) -> str:
    """What a sentence is about ("Halazzi's Rite", "Cleave (2-3 targets)"): the same point on several bosses."""
    text = sentence["text"] if isinstance(sentence, dict) else sentence
    return text.split(":", 1)[0].strip().lower()


def _mmss_(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _li(s) -> str:
    """One point of a boss: a sentence, or a priced finding with what the top players do and the log's moment."""
    if not isinstance(s, dict):
        return f"<li>{e(s)}</li>"
    cost = (f"<b class='lr-cost'>{s['cost']}</b>" if s.get("cost") else
            "<span class='lr-cost np'>&mdash; not priced</span>")  # built here: no user text
    tops = f"<small class='lr-tops'>{e(s['tops'][:1].upper() + s['tops'][1:])}.</small>" if s.get("tops") else ""
    at = f"Open {_mmss_(s['at'])}" if s.get("at") is not None else "Open the pull"
    link = (f" <a class='lr-log' href='{e(s['link'])}' target='_blank' rel='noopener'>{at} on Warcraft Logs &#8599;"
            f"</a>" if s.get("link") else "")
    return f"<li class='lr-pt'>{cost}<span>{e(s['text'])}{link}{tops}</span></li>"


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
        first = first["text"] if isinstance(first, dict) else first
        out.append(first.replace(" on this boss", "").rstrip(".") + f" (on {count[k]} bosses).")
    return out


def headline(slug: str) -> str:
    """One sentence on the last raid read for this character: each boss, killed or how low the best pull got it
    ('' when nothing was read). The home page's line and Reclear's lead."""
    cur = load().get(slug)
    if not cur or not cur.get("bosses"):
        return ""

    def one(b: dict) -> str:
        what = f"{b['name']} {b['difficulty']}"
        if b.get("kill"):
            return f"{what} killed"
        return f"{what}, your best pull got it to {b['best']:.0f}%" if b.get("best") is not None else f"{what}, not killed"
    return "; ".join(one(b) for b in cur["bosses"]) + "."


def card(slug: str, heading: bool = True) -> str:
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
    head = (("<h2>Your last raid</h2>" if heading else "") + f"<p class='lr-sub'>{e(when)} &middot; {_pulls(cur['pulls'])} &middot; {night}"
            f"<a href='{e(URL.format(cur['report']))}' target='_blank' rel='noopener'>the log</a></p>")
    if not cur["bosses"]:
        return f"<section class='lr' id='lastraid'>{head}<p>No boss of the current raid in this log.</p></section>"
    rows, folded = "", ""
    said = [sentences(b, cur["player"]) for b in cur["bosses"]]  # by position: a boss can come in two difficulties
    raid_wide = common(said)
    skip = {_key(x) for x in raid_wide}
    for b, boss_says in zip(cur["bosses"], said, strict=True):
        rot = _result(b["jobs"].get("rotation")) if b["kill"] else None
        reviewed = f" &middot; reviewed: the kill, {_mmss(rot['duration'])}" if rot and rot.get("duration") else ""
        state_txt = (f"killed in {b['pulls']} {'pull' if b['pulls'] == 1 else 'pulls'}{reviewed}" if b["kill"] else
                     f"best pull with the boss at {b['best']:.0f}% health, {_pulls(b['pulls'])}")
        says = ([x for x in boss_says if _key(x) not in skip and not (isinstance(x, dict) and x.get("cmp"))][:3]
                + [x for x in boss_says if isinstance(x, dict) and x.get("cmp")][:6])  # a table: more rows fit
        links = "".join(f"<a href='/job/{e(jid)}'>{label}</a>" for kind, label in
                        (("rotation", "Your rotation"), ("wipe", "Why it did not die"), ("diff", "These two pulls, in detail"))
                        if (jid := b["jobs"].get(kind)) and not _failed(jid))
        if not b["kill"] and (_failed(b["jobs"].get("wipe")) or not b["jobs"].get("wipe")):  # needs the boss prepared
            says = [*says, f"Prepare {b['name']} to see why it did not die, then read the log again."][:3]
        if not says and not cur["finished"]:
            body = "<p class='lr-wait'><span class='pl-spin'></span> Reading&hellip;</p>"
        else:
            rest = [x for x in says if not (isinstance(x, dict) and x.get("cmp"))]
            body = (("<ul>" + "".join(_li(s) for s in rest) + "</ul>" if rest else "")
                    + _cmp_table([x for x in says if isinstance(x, dict) and x.get("cmp")])) if says else \
                "<p class='muted small'>Nothing stands out.</p>"
        card_html = (f"<article class='lr-boss{' kill' if b['kill'] else ''}'><header><b>{e(b['name'])}</b>"
                 f"{diff_pill(b['difficulty'])}<span class='lr-state'>{state_txt}</span></header>"
                 f"{body}<nav class='lr-links'>{links}<a href='/boss?boss={b['boss']}&amp;difficulty={e(b['difficulty'])}'>"
                 f"The prep</a></nav></article>")
        if b["kill"]:
            folded += card_html
        else:
            rows += card_html
    killed = sum(b["kill"] for b in cur["bosses"])
    if folded:  # the bosses killed, after the ones still to kill: in view too (no fold, the user's rule)
        folded = f"<div><h3 class='lr-killed'>Killed ({killed})</h3><div class='lr-grid'>{folded}</div></div>"
    if rows:
        rows = (f"<div><h3 class='lr-killed'>Not killed ({len(cur['bosses']) - killed})</h3>"
                f"<div class='lr-grid'>{rows}</div></div>")
    progress = (f"<p class='lr-wait'><span class='pl-spin'></span> Reading your raid: {done} of {total} analyses"
                f"&hellip;</p>" if not cur["finished"] else "")
    again_btn = ("" if not cur["finished"] or reading else
                 "<form method='post' action='/lastraid/again' class='lr-again'><button class='btn ghost'>Read the "
                 "last log again</button></form>")
    priced = sorted(((x, b["name"]) for b, says in zip(cur["bosses"], said, strict=True) for x in says
                     if isinstance(x, dict) and x.get("value")),  # the simmed costs first, then the upper bounds
                    key=lambda xb: (xb[0].get("approx", False), -xb[0]["value"]))
    def todo(x: dict) -> str:  # the point as an order
        if x.get("kind") == "activity":
            return "keep casting"
        if x.get("kind") == "cooldown":
            return f"press {e(x['name'])} as soon as it is ready"
        return e(x["text"].split(":")[0])
    top = priced[:2]
    if top and all(n == top[0][1] for _x, n in top):  # one boss: said once
        first = (f"<p class='lr-first'>Clean first, on {e(top[0][1])}: "
                 + ", then ".join(f"{todo(x)} ({x['cost']})" for x, _n in top) + ".</p>")
    else:
        first = ("<p class='lr-first'>Clean first: " + "; then ".join(
            f"{todo(x)} on {e(n)} ({x['cost']})" for x, n in top) + ".</p>") if top else ""
    if top:
        first += ("<p class='small muted lr-key'>% of your damage on the pull reviewed, simulated on your character; "
                  "&ldquo;up to&rdquo;: an estimate from the time not casting, part of it movement the fight forces.</p>")
    wide = ("<div class='lr-wide'><b>On the whole raid</b><ul>" + "".join(f"<li>{e(x)}</li>" for x in raid_wide)
            + "</ul></div>") if raid_wide else ""
    return (f"<section class='lr' id='lastraid'{' data-reading=1' if not cur['finished'] else ''}>{head}{progress}"
            f"{first}{wide}<div class='lr-cols'>{folded}{rows}</div>{again_btn}</section>")


CARD_JS = """<script>(function(){var s=document.getElementById('lastraid');if(!s||!s.dataset.reading)return;
setInterval(function(){fetch('/lastraid/card').then(function(r){return r.text()}).then(function(h){
var t=document.createElement('div');t.innerHTML=h;var n=t.firstElementChild;if(!n)return;s.replaceWith(n);s=n;
if(!n.dataset.reading)location.reload()}).catch(function(){})},10000)})();</script>"""


def kill_time(enc_id: int, difficulty: str) -> float | None:
    """How long your raid took to kill this boss in its last log read (the characters' newest first), or None."""
    from paf import characters

    state = load()
    slugs = [characters.current_slug()] + [s for s in state if s != characters.current_slug()]
    for slug in slugs:
        cur = state.get(slug)
        for b in (cur or {}).get("bosses", []) if isinstance(cur, dict) else []:
            if b.get("boss") == enc_id and b.get("difficulty") == difficulty and b.get("kill_time"):
                return float(b["kill_time"])
    return None
