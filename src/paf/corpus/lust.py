"""Bloodlust spots (issue #20): when the top raids use Bloodlust on a boss, read on the whole raid of every kill.

The ranked player's own buffs only show a lust they cast themselves, and never one cast before the pull: on
Nek'zali mythic the Elemental corpus had a lust in 104 of 359 kills (the shamans who cast it), the Rogue corpora in
none. Here one small query per kill reads the lust buffs of every player (~1 point), and the times are grouped into
the spots a raid lead talks about: on pull, at the start of a phase, the last minute, or around a time. A hundred
kills per boss are read, once, in one request each.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections.abc import Callable
from dataclasses import dataclass

from paf.corpus.analyze import kills_filter
from paf.wcl import WCLClient, WCLError

# versioned table of the raid-wide haste buffs (the names depend on the log's language: ids first)
LUST_IDS = {2825: "Bloodlust", 32182: "Heroism", 80353: "Time Warp", 264667: "Primal Rage", 272678: "Primal Rage",
            1242159: "Primal Rage", 390386: "Fury of the Aspects", 466904: "Harrier's Cry",
            444257: "Thunderous Drums", 381301: "Feral Hide Drums", 309658: "Drums of Deathly Ferocity",
            256740: "Drums of the Maelstrom", 230935: "Drums of the Mountain", 178207: "Drums of Fury"}
LUST_SECONDS = 40.0
MIN_PLAYERS = 8  # a lust reaches the whole raid: fewer players gaining it at once is something else
MIN_UP = 15.0  # ... and lasts: a 2 s "Time Warp" or "Fury of the Aspects" is a talent's proc, not a lust
TOGETHER = 3.0  # seconds between the players' gains of one lust

PULL = 10.0  # a lust in the first seconds is "on pull"
PHASE_START = 20.0  # ... within this many seconds of a phase's start is "at the start of the phase"
LAST_MINUTE = 60.0  # ... in the kill's last minute is "the last minute"
CLUSTER = 20.0  # other lusts closer than this belong to the same spot
MIN_SHARE = 0.05  # a spot used by fewer kills is not shown

MAX_KILLS = 100  # kills read per boss: enough for a spot's share, half the cost of a whole corpus
LUST_QUERY = """query($code:String!,$f:[Int]!,$x:String){ reportData { report(code:$code) {
  fights(fightIDs:$f){ startTime endTime }
  events(fightIDs:$f, dataType:Buffs, hostilityType:Friendlies, filterExpression:$x, limit:10000) {
    data nextPageTimestamp } } } }"""


def kill_lust(events: list[dict], start: float, end: float) -> float | None:
    """The raid's first lust in one kill's buff events (ms timestamps), in seconds from the pull; 0 for a lust cast
    before the pull (its buffs only end, about 40 s in); None without one."""
    per: dict[int, list[tuple[float, str]]] = {}
    for ev in sorted(events, key=lambda x: x.get("timestamp", 0)):
        if ev.get("abilityGameID") in LUST_IDS and ev.get("type") in ("applybuff", "removebuff"):
            per.setdefault(ev.get("targetID"), []).append(((ev["timestamp"] - start) / 1000, ev["type"]))
    length = (end - start) / 1000
    gains: list[tuple[float, float]] = []  # (gained at, lasted)
    for evs in per.values():
        up = None
        for t, kind in evs:
            if kind == "applybuff":
                up = t
            elif up is None:  # gained before the pull
                gains.append((t - LUST_SECONDS, LUST_SECONDS))
            else:
                gains.append((up, t - up))
                up = None
        if up is not None:
            gains.append((up, length - up))
    gains.sort()
    for i, (t, _) in enumerate(gains):
        group = [g for g in gains[i:] if g[0] - t <= TOGETHER]
        if len(group) >= MIN_PLAYERS and st.median(d for _, d in group) >= MIN_UP or \
                len(group) >= MIN_PLAYERS and t + st.median(d for _, d in group) >= length - 1:
            return round(max(0.0, st.median(g for g, _ in group)), 1)
    return None


def fetch_lust(client: WCLClient, con: sqlite3.Connection, encounter_id: int, difficulty: int,
               log: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    """Read the raid's lust in up to MAX_KILLS kills of the corpus (one request a kill, read once)."""
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM raid_lust l JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(f"SELECT f.report, f.fight_id FROM fight f LEFT JOIN raid_lust l USING(report, fight_id) "
                       f"WHERE {where} AND l.report IS NULL ORDER BY f.report LIMIT ?",
                       (*params, max(0, MAX_KILLS - have))).fetchall()
    expr = f"ability.id IN ({','.join(map(str, LUST_IDS))})"
    done = 0
    for rep, fid in todo:
        try:
            r = client.query(LUST_QUERY, {"code": rep, "f": [fid], "x": expr}, cache_ttl=0)["reportData"]["report"]
            fr, block = r["fights"][0], r.get("events") or {}
            events = list(block.get("data") or [])
            if block.get("nextPageTimestamp"):  # a long kill: the rest of the pages
                events += list(client.events(rep, fid, block["nextPageTimestamp"], fr["endTime"], data_type="Buffs",
                                             hostility="Friendlies", filter_expression=expr, cache=False))
        except (WCLError, KeyError, TypeError, IndexError, OSError) as e:
            log(f"  lust skipped: {str(e)[:100]}")
            continue
        con.execute("INSERT OR REPLACE INTO raid_lust VALUES(?,?,?)",
                    (rep, fid, kill_lust(events, fr["startTime"], fr["endTime"])))
        done += 1
        if done % 25 == 0:
            con.commit()
    con.commit()
    return done


@dataclass
class Spot:
    kind: str  # pull | phase | last_minute | time | none
    label: str  # "On pull", "Start of Stage Two: Uncoiling", "Last minute", "Around 2:15", "No Bloodlust"
    share: float  # of the kills read
    kills: int
    t: float | None  # the lust time to simulate on the rebuilt fight (None: no lust)
    phase: str = ""  # the phase the spot falls in
    offset: float = 0.0  # seconds after the phase's start (phase) or before the kill's end (last_minute)

    @property
    def phrase(self) -> str:
        """The spot in a sentence: "lust on pull", "lust at the start of Stage Two: Uncoiling"."""
        if self.kind == "pull":
            return "on pull"
        if self.kind == "none":
            return "without Bloodlust"
        if self.kind == "last_minute":
            return "in the last minute"
        if self.kind == "phase":
            return "at the s" + self.label[1:]
        return self.label[0].lower() + self.label[1:]


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def kill_spot(t: float, phases: list[tuple[str, float]], duration: float) -> tuple[str, str, float]:
    """(kind, phase, offset) of one kill's lust: phases are that kill's (name, start), sorted."""
    current = next((p for p in reversed(phases) if p[1] <= t + 1), ("", 0.0))
    if t <= PULL:
        return "pull", current[0], t
    if current[1] > 0 and t - current[1] <= PHASE_START:
        return "phase", current[0], round(max(0.0, t - current[1]), 1)
    if duration - t <= LAST_MINUTE:
        return "last_minute", current[0], round(duration - t, 1)
    return "time", current[0], t


def lust_spots(con: sqlite3.Connection, encounter_id: int, difficulty: int,
               fight_phases: list[tuple[str, float]] | None = None, fight_duration: float | None = None
               ) -> list[Spot]:
    """The usual lust spots of the top raids, most used first. `fight_phases` / `fight_duration`: the rebuilt
    fight's, to place each spot on it (a phase spot at the fight's phase start plus the usual delay)."""
    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(f"SELECT l.report, l.fight_id, l.t, f.duration_s FROM raid_lust l "
                       f"JOIN fight f USING(report, fight_id) WHERE {where}", params).fetchall()
    if not rows:
        return []
    phases: dict[tuple[str, int], list[tuple[str, float]]] = {}
    for rep, fid, name, t in con.execute(
            f"SELECT p.report, p.fight_id, p.name, p.t_start FROM phase p JOIN fight f USING(report, fight_id) "
            f"WHERE {where} ORDER BY p.t_start", params):
        phases.setdefault((rep, fid), []).append((name, t))
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}  # (kind, phase or "") -> [(offset, t)]
    times: list[float] = []
    for rep, fid, t, dur in rows:
        if t is None:
            groups.setdefault(("none", ""), []).append((0.0, 0.0))
            continue
        kind, phase, offset = kill_spot(t, phases.get((rep, fid), []), dur)
        if kind == "time":
            times.append(t)
        else:
            groups.setdefault((kind, phase if kind == "phase" else ""), []).append((offset, t))
    clusters: list[list[float]] = []
    for t in sorted(times):
        if clusters and t - clusters[-1][-1] <= CLUSTER:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    n = len(rows)
    starts: dict[str, list[float]] = {}
    for kill in phases.values():
        for name, t in kill:
            starts.setdefault(name, []).append(t)
    # without the rebuilt fight, the phases' median starts: a spot says the same time on every page
    canon = dict(fight_phases) if fight_phases else {k: st.median(v) for k, v in starts.items()}
    spots = []
    for (kind, phase), v in groups.items():
        offset = st.median(o for o, _ in v)
        if kind == "none":
            spots.append(Spot("none", "No Bloodlust", len(v) / n, len(v), None))
        elif kind == "pull":
            spots.append(Spot("pull", "On pull", len(v) / n, len(v), 0.0, offset=offset))
        elif kind == "phase":
            start = canon.get(phase)
            t = start + offset if start is not None else st.median(x for _, x in v)
            spots.append(Spot("phase", f"Start of {phase}", len(v) / n, len(v), round(t, 1), phase, offset))
        else:
            t = (fight_duration - offset) if fight_duration else st.median(x for _, x in v)
            spots.append(Spot("last_minute", "Last minute", len(v) / n, len(v), round(max(0.0, t), 1), offset=offset))
    for c in clusters:
        t = st.median(c)
        phase = next((p for p, s in reversed(sorted(canon.items(), key=lambda x: x[1])) if s <= t), "")
        spots.append(Spot("time", f"Around {_mmss(t)}", len(c) / n, len(c), round(t, 1), phase))
    return sorted((s for s in spots if s.share >= MIN_SHARE or s.kind == "none"), key=lambda s: -s.share)


def default_lust(spots: list[Spot]) -> float | None:
    """The lust time of the rebuilt fight when the raid lead has not picked a spot: the top raids' most used spot
    (a raid's habit, not the player's choice). None when most top raids do not lust at all."""
    return spots[0].t if spots else 0.0
