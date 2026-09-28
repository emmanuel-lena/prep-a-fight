"""Secondary boss units (a heart, a shield...) from the damage-taken graph of a few kills: when they are
attackable, and how much faster they take damage than the boss (a proxy for their damage amplification)."""

from __future__ import annotations

import sqlite3
import statistics as st
from collections.abc import Callable

from paf.corpus.analyze import kills_filter
from paf.wcl import WCLClient, WCLError

FIGHT_QUERY = """query($code:String!,$f:[Int]!){ reportData { report(code:$code) {
  fights(fightIDs:$f){ startTime endTime } } } }"""
GRAPH_QUERY = """query($code:String!,$f:[Int]!,$s:Float,$e:Float){ reportData { report(code:$code) {
  graph(fightIDs:$f, startTime:$s, endTime:$e, dataType:DamageTaken, hostilityType:Enemies) } } }"""
MIN_SHARE = 0.05  # a boss-type unit must take this share of the enemies' damage to count (else: a mechanic)


def windows_from_series(values: list[float], step: float) -> list[tuple[float, float]]:
    """Contiguous runs of non-zero points -> (start s, duration s)."""
    out, cur = [], None
    for i, v in enumerate(values):
        if v > 0:
            if cur and i == cur[1] + 1:
                cur[1] = i
            else:
                cur = [i, i]
                out.append(cur)
    return [(a * step, (b - a + 1) * step) for a, b in out]


def analyze_graph(series: list[dict], boss_name: str, duration: float) -> list[tuple[str, float, float, float]]:
    """(unit name, start, duration, rate ratio vs the boss outside the unit's windows) per window."""
    by = {s.get("name"): (s.get("type"), s.get("data") or []) for s in series}
    boss = by.get(boss_name, (None, []))[1]
    if not boss:
        return []
    step = duration / len(boss)
    total = sum(sum(v for v in d if isinstance(v, (int, float))) for t, d in by.values() if t in ("Boss", "NPC"))
    out = []
    for name, (kind, data) in by.items():
        if name == boss_name or kind != "Boss" or not data:
            continue
        if sum(data) / (total or 1) < MIN_SHARE:
            continue
        up = {i for i, v in enumerate(data) if v > 0}
        outside = [v for i, v in enumerate(boss) if v > 0 and i not in up]
        if not up or not outside:
            continue
        ratio = (sum(data[i] for i in up) / len(up)) / (sum(outside) / len(outside))
        for start, dur in windows_from_series(data, step):
            if dur >= 2 * step:
                out.append((name, round(start, 1), round(dur, 1), round(ratio, 2)))
    return out


def fetch_unit_windows(client: WCLClient, con: sqlite3.Connection, encounter_id: int, difficulty: int,
                       boss_name: str, kills: int = 12,
                       log: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM unit_status u JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id, f.duration_s FROM fight f LEFT JOIN unit_status u USING(report, fight_id) "
        f"WHERE {where} AND u.report IS NULL ORDER BY f.report LIMIT ?", (*params, max(0, kills - have))).fetchall()
    for r in todo:
        try:
            fr = client.query(FIGHT_QUERY, {"code": r[0], "f": [r[1]]},
                              cache_ttl=0)["reportData"]["report"]["fights"][0]
            g = client.query(GRAPH_QUERY, {"code": r[0], "f": [r[1]], "s": fr["startTime"], "e": fr["endTime"]},
                             cache_ttl=0)["reportData"]["report"]["graph"]
        except (WCLError, KeyError, TypeError, IndexError, OSError) as e:
            log(f"  graph skipped: {str(e)[:100]}")
            continue
        g = g.get("data", g) if isinstance(g, dict) else {}
        rows = analyze_graph(g.get("series") or [], boss_name, (fr["endTime"] - fr["startTime"]) / 1000)
        con.executemany("INSERT INTO unit_window VALUES(?,?,?,?,?,?)", [(r[0], r[1], *x) for x in rows])
        con.execute("INSERT OR REPLACE INTO unit_status VALUES(?,?)", (r[0], r[1]))
        con.commit()
    return len(todo)


TRIGGER_BEFORE = 6.0  # a boss cast ending up to this many seconds before a window can be its trigger
TRIGGER_AFTER = 3.0  # ... or slightly after (the damage graph has a resolution of a few seconds)
TRIGGER_SUPPORT = 0.5  # share of the kills where that cast must precede the window


def trigger_casts(con: sqlite3.Connection, measured: dict[tuple[str, int], list[tuple]],
                  window_time: float, names: dict[int, str]) -> tuple[str, float] | None:
    """The boss cast that opens a window (e.g. a 5 s cast exposing a heart): the ability whose cast
    *ends* right before the window in most kills, and the median time of that cast end."""
    ends: dict[int, list[float]] = {}
    kills = 0
    for (rep, fid), windows in measured.items():
        near = [s for s, _d, _n in windows if abs(s - window_time) <= 15]
        if not near:
            continue
        kills += 1
        w0 = min(near, key=lambda s: abs(s - window_time))
        seen: dict[int, float] = {}
        for aid, t in con.execute(
                "SELECT ability_id, t FROM enemy_cast WHERE report=? AND fight_id=? AND type='cast' "
                "AND t BETWEEN ? AND ?", (rep, fid, w0 - TRIGGER_BEFORE, w0 + TRIGGER_AFTER)):
            seen.setdefault(aid, t)
        for aid, t in seen.items():
            ends.setdefault(aid, []).append(t)
    if not kills or not ends:
        return None
    aid, times = max(ends.items(), key=lambda kv: len(kv[1]))
    if len(times) / kills < TRIGGER_SUPPORT:
        return None
    return names.get(aid, f"spell {aid}"), round(st.median(times), 1)


def unit_windows(con: sqlite3.Connection, encounter_id: int, difficulty: int, min_share: float = MIN_SHARE
                 ) -> tuple[dict[tuple[str, int], list[tuple]], dict[str, float]]:
    """Measured windows per kill {kill: [(start, duration, name)]}, and the median rate ratio of each unit.
    Units taking less than `min_share` of the raid's damage over the corpus are mechanics and are dropped."""
    where, params = kills_filter(encounter_id, difficulty)
    totals = dict(con.execute(
        f"SELECT d.target, SUM(d.amount) FROM damage_by_target d JOIN fight f USING(report, fight_id) "
        f"WHERE {where} GROUP BY d.target", params).fetchall())
    raid = sum(v or 0 for v in totals.values()) or 1
    rows = [r for r in con.execute(
        f"SELECT w.* FROM unit_window w JOIN fight f USING(report, fight_id) WHERE {where}", params).fetchall()
        if (totals.get(r[2]) or 0) / raid >= min_share]
    if not rows:
        return {}, {}
    per_kill: dict[tuple[str, int], list[tuple]] = {}
    ratios: dict[str, list[float]] = {}
    for r in rows:
        per_kill.setdefault((r[0], r[1]), []).append((r[3], r[4], r[2]))
        ratios.setdefault(r[2], []).append(r[5])
    return per_kill, {name: st.median(v) for name, v in ratios.items()}
