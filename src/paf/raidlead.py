"""The raid lead (issue #23): the raid's roles ready-made, so the raid lead thinks about the strategy and not about
"the DH goes single target, the mages AoE".

- The roster: the raid's last log (the active character's last raid, paf.lastraid, else the guild's latest log):
  every player, their spec, their DPS and their talents (one pull of the log). Players can be benched on the page.
- Per boss of the raid (its corpus is needed: a prepared boss), computed on the page from that roster:
  - who hits what: the targets the top raids cannot skip and who of the roster takes them (paf.comp);
  - builds: the talents the top players of each spec take for boss damage and for total damage (the top 100 by boss
    DPS against the top 100 by DPS, paf.wipe.talent_split): a player on an add takes the padding side, a player on
    the boss the boss side, and the page says who should change what;
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
from paf.corpus.memo import by_corpus

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
    from paf.raidneed import RAID_DIFFICULTIES, raid_from_report
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
        rc = raid_from_report(client, url, encs[0].id if encs else 0, diff, {x.id: x.name for x in encs})
        state["players"] = [[n, s, d] for n, s, d in rc.players]
        state["roster_from"] = rc.fight
        # the players' talents, from a pull of the log
        rep = client.query("""query($c:String!){ reportData { report(code:$c) { startTime
          fights(killType: Encounters) { id endTime startTime difficulty } } } }""", {"c": state["report"]},
                           cache_ttl=3600)["reportData"]["report"]
        state["report_day"] = rep.get("startTime")  # how fresh the roster is, said on the page
        fights = sorted(rep.get("fights") or [], key=lambda f: (f.get("difficulty") not in RAID_DIFFICULTIES,
                                                               f["startTime"] - f["endTime"]))
        fight = fights[0]["id"] if fights else None  # the longest raid pull (a key run of the same log: not it)
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


def unread(state: dict, enc_id: int, diff: int) -> list[str]:
    """The players builds() could not check (no talents read, or no build split for their spec): "nobody to
    change" never covers them (a review: Veoxic on an add, unread, under a green "nobody")."""
    out = []
    for name, spec, _dps in state.get("players") or []:
        split = (state.get("splits") or {}).get(f"{enc_id}|{diff}|{spec}") or {}
        if name not in set(state.get("bench") or []) and (not split or not state.get("talents", {}).get(name)):
            out.append(name)
    return out


@by_corpus
def _references(con, encounter_id: int, diff: int, boss: str) -> list:
    """The top raids' targets and who hits them: the corpus only, so kept while it is unchanged (issue #30)."""
    from paf import comp, raidreview

    targets, _habits = raidreview.references(con, encounter_id, diff, boss)
    return comp.references(con, encounter_id, diff, targets)


def sheet(state: dict, enc, diff: int) -> dict | None:
    """One boss for the roster (the benched players out): who hits what, builds."""
    from paf import comp
    from paf.corpus import db
    from paf.corpus.analyze import main_boss
    from paf.raidneed import RaidComp

    con = db.connect()
    if not _has_corpus(con, enc.id, diff):
        return None
    bench = set(state.get("bench") or [])
    players = [(n, s, d) for n, s, d in state.get("players") or [] if n not in bench]
    rc = RaidComp(state.get("report", ""), state.get("roster_from", ""), players, {}, 0.0, False)
    refs = _references(con, enc.id, diff, main_boss(con, enc.id, diff, enc.name))
    rows = comp.assign(rc, refs)
    roles: dict[str, str] = {}
    for a in rows:
        for n, _s in a.proposed:
            roles[n] = "pad"
    try:
        from paf.gamedata import talent_entry_names

        names = talent_entry_names()
    except Exception:  # noqa: BLE001
        names = {}
    from paf.corpus.lust import lust_spots

    spots = lust_spots(con, enc.id, diff)
    pick = lust_pick(enc.id, diff)
    return {"boss": enc.name, "targets": [{"name": a.target, "whole_raid": a.whole_raid, "second_boss": a.second_boss,
                                           "players": [n for n, _s in a.proposed],
                                           "best": [s for s, _d, _n in a.ranking[:3]]} for a in rows],
            "builds": builds(state, enc.id, diff, roles, names),
            "unread": unread(state, enc.id, diff),
            "enc": enc.id, "diff": diff, "lust": spots, "lust_pick": pick if any(x.label == pick for x in spots) else "",
            "lust_kills": con.execute("SELECT COUNT(*) FROM raid_lust l JOIN fight f USING(report, fight_id) "
                                      "WHERE f.encounter_id=? AND f.difficulty=? AND f.status='done'",
                                      (enc.id, diff)).fetchone()[0],
            "lust_gains": lust_gains(enc.name, diff)}


def lust_gains(boss: str, diff: int) -> tuple[str, dict[str, list], float, float] | None:
    """What each Bloodlust spot gives in the newest prep of this boss on this machine: (spec, {spot: [total %,
    boss %]}, noise %, the prep's kill time), from the sheet's summary (paf.cli prep)."""
    from paf import settings
    from paf.corpus.template import _slug
    from paf.web import prepared

    name = next((n for n, v in settings.DIFFICULTIES.items() if v == diff), "")
    for item in prepared():  # newest first
        lust = (item.get("headline") or {}).get("lust")
        if lust and item["key"].startswith(f"{_slug(boss)}-{name}-"):
            return lust.get("spec", ""), lust.get("spots", {}), lust.get("noise", 0.0), lust.get("kill", 0.0)
    return None


def lust_spot(sh: dict):
    """The spot the raid plays: the raid lead's pick, else the top raids' most used one."""
    return next((x for x in sh.get("lust") or [] if x.label == sh.get("lust_pick")), None) or \
        next(iter(sh.get("lust") or []), None)


def _ic(spec: str) -> str:
    """A player's class icon from its spec ("Frost DeathKnight" -> the Death Knight's)."""
    from paf import icons

    cls = (spec or "").split(" ")[-1].lower()
    return icons.img(icons.CLASS_ICON.format(cls=cls), "small", "ics") if cls else ""


def pretty(spec: str) -> str:
    """"BeastMastery Hunter" -> "Beast Mastery Hunter", "Frost DeathKnight" -> "Frost Death Knight"."""
    import re

    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", spec)


def text(sh: dict, difficulty: str, mrt: bool = False) -> str:
    """The sheet as text: for Discord (bold boss line) or an MRT note (plain)."""
    lines = [f"{sh['boss']} ({difficulty})" if mrt else f"**{sh['boss']} ({difficulty})**"]
    if (spot := lust_spot(sh)) is not None:
        lines.append(f"Bloodlust: {spot.label.lower() if spot.kind != 'none' else 'none'}")
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
    if len(lines) == 1 + (lust_spot(sh) is not None):
        lines.append("Everyone on the boss, no change.")
    return "\n".join(lines)


def _tools() -> str:
    from paf import workshop

    return (f"<h2>Dig deeper into your raid's log</h2>{workshop.cards(('review', 'comp', 'raid', 'night'))}"
            f"<h2>The boss, for your assignments</h2>{workshop.cards(('assigns', 'mechanics'))}"
            "<p class='muted'>Your own play, pull by pull, is on <a href='/reclear'>Reclear</a>.</p>"
            f"{workshop.CSS}")


def page_body(difficulty: str) -> str:
    from paf import settings
    from paf.prep_report import copy_button
    from paf.web import DIFF_LABELS, _encounters, journal_order

    state = load()
    diff = settings.DIFFICULTIES.get(difficulty, 4)
    diffs = "".join(f'<label class="seg"><input type="radio" name="difficulty" value="{d}"{" checked" if d == difficulty else ""} '
                    f'onchange="this.form.submit()"><span>{e(DIFF_LABELS.get(d, d))}</span></label>'
                    for d in settings.DIFFICULTIES if d != "lfr")
    lead = ("<p class='lead'>Your raid's roles on every boss, from your roster and the top raids: who hits which "
            "add, who changes talents, which spec change is worth it. The strategy stays yours.</p>")
    head = (f"<h1>Raid lead</h1>{lead}<form method='get' action='/raidlead' class='segs' role='radiogroup' "
            f"aria-label='Difficulty'>{diffs}</form>")
    try:
        code = None if state.get("players") or state.get("error") else source_log()
    except Exception:  # noqa: BLE001 - offline: the button stays
        code = None
    if code and state.get("auto") != code and not runner_alive(state):  # the page opens on the answer: the roster
        state["auto"] = code                                               # is read once by itself, per log
        save(state)
        start(difficulty, code)
        state = load()
    reading = runner_alive(state)
    if reading:
        return head + ("<div class='rl-wait' id='rlwait'><span class='pl-spin'></span> Reading your roster and the "
                       "top players' talents of its specs&hellip; this page updates by itself.</div>"
                       "<script>setTimeout(function(){location.reload()},10000)</script>")
    if not state.get("players"):
        err = f"<p class='notice'>{e(state['error'])}</p>" if state.get("error") else ""
        g = settings.get("guild")
        src = (f"your last raid (read when the app starts), else the latest log of {e(g)}" if g else
               "your last raid (read when the app starts), else your guild's latest log (set it in "
               "<a href='/settings'>Settings</a>)")
        return head + (f"{err}<section class='rl-start'><h2>First, your raid's roster</h2><p>Every answer on this "
                       f"page starts from who is in your raid. The button reads {src}: about a minute.</p>"
                       f"<form method='post' action='/raidlead/read'><input type='hidden' name='difficulty' "
                       f"value='{e(difficulty)}'><button class='btn go'>Read my raid's roster</button></form></section>"
                       + _tools())
    bench = set(state.get("bench") or [])
    chips = "".join(
        f"<form method='post' action='/raidlead/bench' class='rl-p{' off' if n in bench else ''}'>"
        f"<input type='hidden' name='name' value='{e(n)}'><button type='submit' title='"
        f"{'Back in the raid' if n in bench else 'Bench'}'>{_ic(s)}<b>{e(n)}</b><small>{e(pretty(s))}</small></button></form>"
        for n, s, _d in sorted(state["players"], key=lambda p: p[1]))
    day = state.get("report_day")
    when = time.strftime(" (%a %d %b)", time.localtime(day / 1000)) if day else ""
    roster = (f"<section class='rl-roster'><h2>Your roster</h2><p class='small muted'>From {e(state.get('roster_from', ''))}{when} "
              f"of <a href='https://www.warcraftlogs.com/reports/{e(state['report'])}' target='_blank' rel='noopener'>"
              f"this log</a>. Click a player to bench them.</p><div class='rl-chips'>{chips}</div>"
              f"<form method='post' action='/raidlead/read'><input type='hidden' name='difficulty' value='{e(difficulty)}'>"
              f"<button class='btn ghost'>Read the roster again</button></form></section>")
    spec_of = {n: sp for n, sp, _d in state["players"]}  # a player's class icon beside its name
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
        tg = "".join(  # a row a target: who in your raid, the specs the top raids put on it (the owner: less text;
            # "best specs in the top raids" said once, in the header)
            f"<tr><td><b>{e(t['name'])}</b></td><td>" + (
                "everyone" if t["whole_raid"] and not t["players"] else
                ("".join(f"<span class='rl-n'>{_ic(spec_of.get(n, ''))}{e(n)}</span>" for n in t["players"])
                 if t["players"] else "<span class='muted'>nobody fits</span>"))
            + "</td><td>" + ("<span class='rl-side'>a second boss</span>" if t["second_boss"] else
                             " ".join(f"<span class='rl-best'>{_ic(b)}{e(pretty(b))}</span>" for b in t["best"]))
            + "</td></tr>" for t in sh["targets"])
        tg = (f"<table class='rl-tg'><thead><tr><th>Target</th><th>Your raid</th><th>Best specs in the top raids</th>"
              f"</tr></thead><tbody>{tg}</tbody></table>") if tg else ""
        bd = "".join(  # one line a player: who, which build, then each talent to take (+) or drop (-)
            f"<li class='rl-b'>{_ic(b['spec'])}<b>{e(b['name'])}</b><small>{e(pretty(b['spec']))}</small>"
            f"<span class='rl-side {'pad' if b['side'] == 'pad' else 'boss'}'>"
            f"{'pad build &middot; on an add' if b['side'] == 'pad' else 'boss build'}</span>"
            + "<span class='rl-ts'>" + "".join(f"<span class='rl-t take'>+ {e(t)}</span>" for t in b["take"])
            + "".join(f"<span class='rl-t drop'>&minus; {e(t)}</span>" for t in b["drop"]) + "</span></li>"
            for b in sh["builds"])
        cards += (f"<article class='rl-boss' id='boss-{x.id}'><header><h3>{e(x.name)}</h3>"
                  f"{copy_button(text(sh, difficulty), 'Copy for Discord')}"
                  f"{copy_button(text(sh, difficulty, mrt=True), 'Copy MRT note')}</header>"
                  f"<h4>Who hits what</h4>{tg or '<p>Everyone on the boss: no add to assign.</p>'}"
                  + (f"<h4>Talents to change</h4><ul>{bd}</ul>" if bd else  # "not a sim": the legend, once
                     ("<h4>Talents to change <span class='rl-ok'>&#10003; nobody, from the log</span></h4>"
                      if not sh.get("unread") else
                      f"<h4>Talents to change <span class='rl-unread'>? {len(sh['unread'])} "
                      f"player{'s' if len(sh['unread']) > 1 else ''} not read: {e(', '.join(sh['unread']))}</span></h4>"))
                  + lust_block(sh, difficulty) + "</article>")
    allbtn = (copy_button("\n\n".join(text(sh, difficulty) for sh in everything), "Copy every boss for Discord")
              if everything else "")
    miss = (f"<p class='small muted'>Not prepared yet, so no sheet: {e(', '.join(missing))}. "
            f"<a href='/raid/prepare?difficulty={e(difficulty)}'>Prepare the whole raid</a> first.</p>" if missing else "")
    n = len(everything)
    answer = (f"<p class='lead'>{n} {'boss' if n == 1 else 'bosses'} to copy for Discord"
              + (f", {len(missing)} still to prepare" if missing else "")
              + f", for the {len(state['players']) - len(bench)} players of your raid.</p>") if n else ""
    if answer:  # the answer is the page's lead; what the page does goes
        head = head.replace(lead, answer)
    words = ("<p class='rl-words'>Pad build: the talents for an add (more targets); boss build: for single target; "
             "both the top players' builds, not a sim. The MRT note is the text the Method Raid Tools "
             "addon shows in game.</p>"
             ) if everything else ""
    return (head + roster + f"<h2>Boss by boss</h2><div class='rl-all'>{allbtn}</div>{miss}{words}<div class='rl-grid'>{cards}</div>"
            f"{_tools()}{COPY_JS}")


def lust_block(sh: dict, difficulty: str) -> str:
    """The top raids' Bloodlust spots on a boss, how often each is used, what it gives in the newest prep here, and
    the raid lead's pick (used by the preps of this app, and written in the Discord text)."""
    spots = sh.get("lust") or []
    if not spots:
        return ""
    current = lust_spot(sh)
    spec, gains, noise, kill = sh.get("lust_gains") or ("", {}, 0.0, 0.0)
    rows = ""
    for x in spots:
        g = gains.get(x.label)
        if not g or g[0] is None:
            gain = ""
        elif g[0] == 0:
            gain = "<span class='rl-gain ref'>baseline</span>"
        else:
            gain = (f"<span class='rl-gain {'pos' if g[0] > 0 else 'neg'}'>{_signed(g[0])}%"
                    + (f"<small>&plusmn;{noise:.1f}%</small>" if noise else "") + "</span>")
        when = (f", <span class='t'>{_mmss(x.t)}</span>" if x.t is not None and x.kind not in ("pull", "none")
                else "")
        where = f" · in {e(x.phase)}" if x.phase and x.kind in ("time", "last_minute") else ""
        rows += (f"<label class='rl-lust'><input type='radio' name='spot' value='{e(x.label)}'"
                 f"{' checked' if x is current else ''} onchange='this.form.submit()'>"
                 f"<span class='rl-what'><b>{e(x.label)}{when}</b><small>{x.share:.0%} of the top raids{where}</small>"
                 f"</span>{gain}</label>")
    best = max(((x, gains[x.label][0]) for x in spots if x.t is not None and gains.get(x.label)
                and gains[x.label][0] is not None), key=lambda xg: xg[1], default=None)
    lead = ""
    if best is not None and best[1] > max(noise, 0.1):
        base = next((x for x in spots if (gains.get(x.label) or [None])[0] == 0), None)
        x = best[0]
        lead = (f"<p class='rl-lead'>Lust {e(x.phrase)}: {_signed(best[1])}% damage for the {e(spec)} prep"
                + (f" over lust {e(base.phrase)}" if base else "") + ".</p>"
                "<p class='rl-intro'>The top raids are split: "
                + ", ".join(f"{y.share:.0%} {e(y.phrase)}" for y in spots if y.t is not None) + ".</p>")
    who = ("Your pick goes into your preps here and into the Discord text." if sh.get("lust_pick") else
           "Checked by default: the top raids' most used spot, since lust timing is a raid-wide call and one spec's "
           "gain is only a hint. Your pick goes into your preps here and into the Discord text.")
    rest = 1 - sum(x.share for x in spots)
    notes = [f"{rest:.0%} of the top raids lust elsewhere, each spot under 5%."] if rest >= 0.03 else []
    notes.append(f"Simmed on the newest {e(spec)} prep here{f' ({_mmss(kill)} kill)' if kill else ''}, with "
                 f"Bloodlust at each spot against the spot it played (baseline). Other specs may gain differently."
                 if gains else "Prepare this boss to see what each spot gives.")
    return (f"<h4>Bloodlust</h4>{lead}<p class='rl-intro'>{sh.get('lust_kills', 0)} top kills read. {who}</p>"
            f"<form method='post' action='/raidlead/lust' class='rl-lusts' role='radiogroup' aria-label='Bloodlust'>"
            f"<input type='hidden' name='enc' value='{sh['enc']}'><input type='hidden' name='diff' value='{sh['diff']}'>"
            f"<input type='hidden' name='difficulty' value='{e(difficulty)}'>{rows}</form>"
            f"<p class='rl-note'>{' '.join(notes)}</p>")


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _signed(v: float) -> str:
    return f"+{v:.1f}" if v > 0 else f"\u2212{abs(v):.1f}"  # a true minus sign


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


def lust_pick(enc_id: int, diff: int) -> str:
    """The Bloodlust spot the raid lead picked for a boss (a paf.corpus.lust.Spot label), "" for none."""
    return (load().get("lust") or {}).get(f"{enc_id}-{diff}", "")


def set_lust(enc_id: int, diff: int, label: str) -> None:
    state = load()
    picks = state.setdefault("lust", {})
    if label:
        picks[f"{enc_id}-{diff}"] = label
    else:
        picks.pop(f"{enc_id}-{diff}", None)
    save(state)
