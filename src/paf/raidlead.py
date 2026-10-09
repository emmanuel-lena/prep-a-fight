"""The raid lead (issue #23): the raid's roles ready-made, so the raid lead thinks about the strategy and not about
"the DH goes single target, the mages AoE".

- The roster: the raid's last log (the active character's last raid, paf.lastraid, else the guild's latest log):
  every player, their spec, their DPS and their talents (one pull of the log). Players can be benched on the page.
- Per boss of the raid (its corpus is needed: a prepared boss), computed on the page from that roster:
  - who hits what: the targets the top raids cannot skip and who of the roster takes them (paf.comp);
  - builds: the talents the top players of each spec take for boss damage and for total damage (the top 100 by boss
    DPS against the top 100 by DPS, paf.wipe.talent_split): a player on an add takes the padding side, a player on
    the boss the boss side, and the page says who should change what;
  - the spec changes worth it for boss damage (paf.comp.swaps).
- A text to paste in Discord and an MRT note, one line per target and per player to change.
- A background process (`paf raidlead`) reads the roster and the talent rankings (the slow part: two rankings per
  spec and boss, cached); the rest is computed when the page shows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from html import escape as e
from pathlib import Path

from paf.config import data_dir

TALENT_GAP = 0.15  # as paf.wipe: a talent taken this much more on one side is a side's talent
SHOWN = 3


def _path() -> Path:
    return data_dir() / "web" / "raidlead.json"


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


def runner_alive(state: dict | None = None) -> bool:
    from paf.web import pid_alive

    state = load() if state is None else state
    return bool(state.get("pid") and pid_alive(state["pid"]))


def source_log() -> str | None:
    """The raid's last log: the active character's last raid, else the guild's latest log."""
    from paf import characters, lastraid, settings

    cur = lastraid.load().get(characters.current_slug())
    if cur and cur.get("report") and cur.get("bosses"):
        return cur["report"]
    if settings.get("guild"):
        from paf.raidneed import GUILD_REPORTS_QUERY, server_slug
        from paf.wcl import WCLClient

        data = WCLClient().query(GUILD_REPORTS_QUERY, {"name": settings.get("guild"),
                                                       "server": server_slug(settings.get("guild_server")),
                                                       "region": settings.get("guild_region").upper()}, cache_ttl=900)
        reports = (data["reportData"]["reports"] or {}).get("data") or []
        return reports[0]["code"] if reports else None
    return None


def start(difficulty: str, code: str | None = None) -> bool:
    """Read the roster and the talents in the background."""
    from paf.web import _env, _python

    if runner_alive():
        return False
    code = code or source_log()
    if not code:
        return False
    state = load()
    state.update(difficulty=difficulty, report=code, pid=None, error="")
    save(state)
    folder = data_dir() / "web"
    flags = 0x00000008 | 0x08000000 if sys.platform == "win32" else 0  # DETACHED_PROCESS, CREATE_NO_WINDOW
    with (folder / "raidlead.log").open("a", encoding="utf-8") as out:
        subprocess.Popen([_python(), "-m", "paf", "raidlead"], stdout=out, stderr=subprocess.STDOUT,
                         creationflags=flags, env={**_env(), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                         **({} if sys.platform == "win32" else {"start_new_session": True}))
    return True


def _has_corpus(con, enc_id: int, diff: int) -> bool:
    return bool(con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                            (enc_id, diff)).fetchone()[0])


def run(log=print) -> int:
    """The reader: the roster of the log, its talents, and the talent rankings of its specs on every prepared boss."""
    from paf import settings
    from paf.corpus import db
    from paf.raidneed import raid_from_report
    from paf.wcl import WCLClient
    from paf.web import _encounters, journal_order
    from paf.wipe import DETAILS, talent_split

    state = load()
    if runner_alive(state) and state["pid"] != os.getpid():
        return 0
    state["pid"] = os.getpid()
    save(state)
    try:
        client = WCLClient()
        diff = settings.DIFFICULTIES.get(state.get("difficulty") or "heroic", 4)
        encs = journal_order(_encounters())
        url = f"https://www.warcraftlogs.com/reports/{state['report']}"
        rc = raid_from_report(client, url, encs[0].id if encs else 0, diff)
        state["players"] = [[n, s, d] for n, s, d in rc.players]
        state["roster_from"] = rc.fight
        # the players' talents, from a pull of the log
        rep = client.query("""query($c:String!){ reportData { report(code:$c) {
          fights(killType: Encounters) { id endTime startTime } } } }""", {"c": state["report"]},
                           cache_ttl=3600)["reportData"]["report"]
        fights = sorted(rep.get("fights") or [], key=lambda f: f["startTime"] - f["endTime"])
        fight = fights[0]["id"] if fights else None  # the longest pull
        talents: dict[str, list[int]] = {}
        if fight:
            data = client.query(DETAILS, {"c": state["report"], "f": [fight]}, cache_ttl=86400)
            data = data["reportData"]["report"]["playerDetails"]
            data = data.get("data", data) if isinstance(data, dict) else {}
            data = data.get("playerDetails", data)
            for role in ("dps", "tanks", "healers"):
                for x in data.get(role) or []:
                    talents[x["name"]] = [t.get("id") for t in (x.get("combatantInfo") or {}).get("talentTree") or []]
        state["talents"] = talents
        save(state)
        con = db.connect()
        from paf.raidreview import _damage_spec

        specs = sorted({s for _n, s, _d in rc.players if _damage_spec(s)})  # healers and tanks: no build advice
        splits = state.get("splits") or {}
        for x in encs:
            if not _has_corpus(con, x.id, diff):
                continue
            for spec in specs:
                key = f"{x.id}|{diff}|{spec}"
                if key not in splits:
                    try:
                        splits[key] = {str(t): v for t, v in talent_split(client, x.id, diff, spec).items()}
                    except Exception as ex:  # noqa: BLE001 - a spec without rankings: no build advice for it
                        log(f"{spec} on {x.name}: {ex}")
                        splits[key] = {}
            state["splits"] = splits
            save(state)
        state["built"] = time.time()
    except Exception as ex:  # noqa: BLE001 - shown on the page
        state["error"] = str(ex)
        log(f"raid lead: {ex}")
    finally:
        state["pid"] = None
        save(state)
    return 0


# --- the sheets ---------------------------------------------------------------------------------------------------

def builds(state: dict, enc_id: int, diff: int, roles: dict[str, str], names: dict[int, str]) -> list[dict]:
    """Who should change talents on this boss: a player on an add or a second boss takes the padding side, a player
    on the boss the boss side. [{name, spec, side, take, drop}]"""
    out = []
    for name, spec, _dps in state.get("players") or []:
        split = (state.get("splits") or {}).get(f"{enc_id}|{diff}|{spec}") or {}
        taken = set(state.get("talents", {}).get(name) or [])
        if not split or not taken:
            continue
        side = roles.get(name, "boss")
        pad = {int(t) for t, (a, b) in split.items() if a - b >= TALENT_GAP}
        boss = {int(t) for t, (a, b) in split.items() if b - a >= TALENT_GAP}
        want, other = (pad, boss) if side == "pad" else (boss, pad)
        take = [names.get(t) or "" for t in sorted(want - taken)]
        drop = [names.get(t) or "" for t in sorted(other & taken)]
        both = set(take) & set(drop)
        take = [n for n in dict.fromkeys(take) if n and n not in both][:SHOWN]
        drop = [n for n in dict.fromkeys(drop) if n and n not in both][:SHOWN]
        if take or drop:
            out.append({"name": name, "spec": spec, "side": side, "take": take, "drop": drop})
    return out


def sheet(state: dict, enc, diff: int) -> dict | None:
    """One boss for the roster (the benched players out): who hits what, builds, spec changes."""
    from paf import comp, raidplan, raidreview
    from paf.corpus import db
    from paf.corpus.analyze import main_boss
    from paf.raidneed import RaidComp

    con = db.connect()
    if not _has_corpus(con, enc.id, diff):
        return None
    bench = set(state.get("bench") or [])
    players = [(n, s, d) for n, s, d in state.get("players") or [] if n not in bench]
    rc = RaidComp(state.get("report", ""), state.get("roster_from", ""), players, {}, 0.0, False)
    boss = main_boss(con, enc.id, diff, enc.name)
    targets, _habits = raidreview.references(con, enc.id, diff, boss)
    refs = comp.references(con, enc.id, diff, targets)
    rows = comp.assign(rc, refs)
    roles: dict[str, str] = {}
    for a in rows:
        for n, _s in a.proposed:
            roles[n] = "pad"
    bosses = {boss} | {r.name for r in refs if r.second_boss}
    swaps = comp.swaps(rc, comp.boss_dps(con, enc.id, diff, bosses), raidplan.class_specs(con, enc.id, diff))
    try:
        from paf.gamedata import talent_entry_names

        names = talent_entry_names()
    except Exception:  # noqa: BLE001
        names = {}
    return {"boss": enc.name, "targets": [{"name": a.target, "whole_raid": a.whole_raid, "second_boss": a.second_boss,
                                           "players": [n for n, _s in a.proposed],
                                           "best": [s for s, _d, _n in a.ranking[:3]]} for a in rows],
            "builds": builds(state, enc.id, diff, roles, names),
            "swaps": [{"name": x.name, "current": x.current, "better": x.better, "gain": x.gain} for x in swaps]}


def pretty(spec: str) -> str:
    """"BeastMastery Hunter" -> "Beast Mastery Hunter", "Frost DeathKnight" -> "Frost Death Knight"."""
    import re

    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", spec)


def text(sh: dict, difficulty: str, mrt: bool = False) -> str:
    """The sheet as text: for Discord (bold boss line) or an MRT note (plain)."""
    lines = [f"{sh['boss']} ({difficulty})" if mrt else f"**{sh['boss']} ({difficulty})**"]
    for t in sh["targets"]:
        if t["whole_raid"] and not t["players"]:
            lines.append(f"{t['name']}: everyone")
        elif t["players"]:
            lines.append(f"{t['name']}: {', '.join(t['players'])}")
    for b in sh["builds"]:
        what = "padding talents" if b["side"] == "pad" else "boss talents"
        change = (f"take {', '.join(b['take'])}" if b["take"] else "") + (
            (" / " if b["take"] and b["drop"] else "") + f"drop {', '.join(b['drop'])}" if b["drop"] else "")
        lines.append(f"{b['name']} ({what}): {change}")
    for s in sh["swaps"]:
        lines.append(f"{s['name']}: {pretty(s['better'])} does {s['gain']:+.0%} boss damage vs {pretty(s['current'])}")
    if len(lines) == 1:
        lines.append("Everyone on the boss, no change.")
    return "\n".join(lines)


def page_body(difficulty: str) -> str:
    from paf import settings
    from paf.prep_report import copy_button
    from paf.web import DIFF_LABELS, _encounters, journal_order

    state = load()
    diff = settings.DIFFICULTIES.get(difficulty, 4)
    diffs = "".join(f'<label class="seg"><input type="radio" name="difficulty" value="{d}"{" checked" if d == difficulty else ""} '
                    f'onchange="this.form.submit()"><span>{e(DIFF_LABELS.get(d, d))}</span></label>'
                    for d in settings.DIFFICULTIES if d != "lfr")
    head = (f"<h1>Raid lead</h1><p class='lead'>Your raid's roles on every boss, from your roster and the top raids: "
            f"who hits which add, who changes talents, which spec change is worth it. You think about the strategy."
            f"</p><form method='get' action='/raidlead' class='segs' role='radiogroup' aria-label='Difficulty'>{diffs}"
            f"</form>")
    reading = runner_alive(state)
    if reading:
        return head + ("<div class='rl-wait' id='rlwait'><span class='pl-spin'></span> Reading your roster and the "
                       "top players' talents of its specs&hellip; this page updates by itself.</div>"
                       "<script>setTimeout(function(){location.reload()},10000)</script>")
    if not state.get("players"):
        err = f"<p class='notice'>{e(state['error'])}</p>" if state.get("error") else ""
        return head + (f"{err}<div class='rl-start'><p>The roster comes from your raid's last log: your last raid "
                       f"(read when the app starts), else your guild's latest log (Settings).</p>"
                       f"<form method='post' action='/raidlead/read'><input type='hidden' name='difficulty' "
                       f"value='{e(difficulty)}'><button class='btn'>Read my raid's roster</button></form></div>")
    bench = set(state.get("bench") or [])
    chips = "".join(
        f"<form method='post' action='/raidlead/bench' class='rl-p{' off' if n in bench else ''}'>"
        f"<input type='hidden' name='name' value='{e(n)}'><button type='submit' title='"
        f"{'Back in the raid' if n in bench else 'Bench'}'><b>{e(n)}</b><small>{e(pretty(s))}</small></button></form>"
        for n, s, _d in sorted(state["players"], key=lambda p: p[1]))
    roster = (f"<section class='rl-roster'><h2>Your roster</h2><p class='small muted'>From {e(state.get('roster_from', ''))} "
              f"of <a href='https://www.warcraftlogs.com/reports/{e(state['report'])}' target='_blank' rel='noopener'>"
              f"this log</a>. Click a player to bench them.</p><div class='rl-chips'>{chips}</div>"
              f"<form method='post' action='/raidlead/read'><input type='hidden' name='difficulty' value='{e(difficulty)}'>"
              f"<button class='btn ghost'>Read the roster again</button></form></section>")
    cards, missing = "", []
    everything = []
    for x in journal_order(_encounters()):
        try:
            sh = sheet(state, x, diff)
        except Exception as ex:  # noqa: BLE001 - one boss never hides the others
            cards += f"<article class='rl-boss'><h3>{e(x.name)}</h3><p class='notice'>{e(str(ex))}</p></article>"
            continue
        if sh is None:
            missing.append(x.name)
            continue
        everything.append(sh)
        tg = "".join(
            f"<li><b>{e(t['name'])}</b>: " + (
                "everyone" if t["whole_raid"] and not t["players"] else
                (e(", ".join(t["players"])) if t["players"] else "<span class='muted'>nobody fits</span>"))
            + (f" <small>({'second boss' if t['second_boss'] else 'best: ' + e(', '.join(pretty(b) for b in t['best']))})</small>")
            + "</li>" for t in sh["targets"])
        bd = "".join(
            f"<li><b>{e(b['name'])}</b> <small>{e(pretty(b['spec']))}, "
            f"{'on an add: padding talents' if b['side'] == 'pad' else 'on the boss: boss talents'}</small>"
            + (f"<br>take {e(', '.join(b['take']))}" if b["take"] else "")
            + (f"<br>drop {e(', '.join(b['drop']))}" if b["drop"] else "") + "</li>" for b in sh["builds"])
        sw = "".join(f"<li><b>{e(s['name'])}</b>: {e(pretty(s['better']))} does {s['gain']:+.0%} boss damage vs "
                     f"{e(pretty(s['current']))}</li>" for s in sh["swaps"])
        cards += (f"<article class='rl-boss'><header><h3>{e(x.name)}</h3>"
                  f"{copy_button(text(sh, difficulty), 'Copy for Discord')}"
                  f"{copy_button(text(sh, difficulty, mrt=True), 'Copy MRT note')}</header>"
                  f"<h4>Who hits what</h4><ul>{tg or '<li>Everyone on the boss: no add to assign.</li>'}</ul>"
                  + (f"<h4>Talents to change</h4><ul>{bd}</ul>" if bd else
                     "<h4>Talents</h4><p class='small muted'>Nobody needs to change, from what the log shows.</p>")
                  + (f"<h4>Spec changes worth it</h4><ul>{sw}</ul>" if sw else "") + "</article>")
    allbtn = (copy_button("\n\n".join(text(sh, difficulty) for sh in everything), "Copy every boss for Discord")
              if everything else "")
    miss = (f"<p class='small muted'>Not prepared yet, so no sheet: {e(', '.join(missing))}. "
            f"<a href='/raid/prepare?difficulty={e(difficulty)}'>Prepare the whole raid</a> first.</p>" if missing else "")
    return head + roster + f"<h2>Boss by boss {allbtn}</h2>{miss}<div class='rl-grid'>{cards}</div>{COPY_JS}"


COPY_JS = """<script>document.addEventListener('click',function(ev){var b=ev.target.closest('.copy');if(!b)return;
var t=b.dataset.copy,label=b.textContent;function done(){b.textContent='Copied';setTimeout(function(){b.textContent=label},1500)}
if(navigator.clipboard){navigator.clipboard.writeText(t).then(done,function(){fallback()})}else{fallback()}
function fallback(){var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
try{document.execCommand('copy');done()}catch(e){}a.remove()}});</script>"""


def toggle_bench(name: str) -> None:
    state = load()
    bench = set(state.get("bench") or [])
    bench ^= {name}
    state["bench"] = sorted(bench)
    save(state)
