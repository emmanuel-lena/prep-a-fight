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


AURA_QUERY = """query($code:String!,$f:[Int]!,$s:Float,$e:Float){ reportData { report(code:$code) {
  masterData { actors(type:"NPC") { id name subType } }
  debuffs: events(fightIDs:$f, startTime:$s, endTime:$e, dataType:Debuffs, hostilityType:Enemies, limit:10000) {
    data nextPageTimestamp }
  buffs: events(fightIDs:$f, startTime:$s, endTime:$e, dataType:Buffs, hostilityType:Enemies, limit:10000) {
    data nextPageTimestamp }
  graph(fightIDs:$f, startTime:$s, endTime:$e, dataType:DamageTaken, hostilityType:Enemies)
} } }"""
AMP_MIN_RATIO = 1.3  # a boss aura during which the boss takes damage this much faster is a candidate amp


def aura_windows(events: list[dict], boss_ids: set[int], enemy_ids: set[int], start: float, end: float
                 ) -> dict[int, list[tuple[float, float]]]:
    """Windows of the auras applied to the boss by enemies (or the environment), per ability."""
    open_: dict[tuple[int, int], float] = {}
    out: dict[int, list[tuple[float, float]]] = {}
    for ev in events:
        if ev.get("targetID") not in boss_ids:
            continue
        src = ev.get("sourceID", -1)
        if src not in enemy_ids and src != -1:
            continue  # applied by a player: dots, raid debuffs...
        aid, t = ev.get("abilityGameID"), (ev["timestamp"] - start) / 1000
        typ = ev.get("type", "")
        if typ.startswith("apply") and not typ.endswith("stack"):
            open_[(aid, ev["targetID"])] = t
        elif typ.startswith("remove") and not typ.endswith("stack") and (aid, ev["targetID"]) in open_:
            t0 = open_.pop((aid, ev["targetID"]))
            out.setdefault(aid, []).append((t0, t - t0))
    for (aid, _), t0 in open_.items():
        out.setdefault(aid, []).append((t0, (end - start) / 1000 - t0))
    return out


def rate_ratio(series: list[float], step: float, windows: list[tuple[float, float]]) -> float | None:
    inside = {i for s, d in windows for i in range(int(s / step), min(len(series), int((s + d) / step) + 1))}
    a = [series[i] for i in inside if series[i] > 0]
    b = [v for i, v in enumerate(series) if i not in inside and v > 0]
    if len(a) < 2 or len(b) < 2:
        return None
    return (sum(a) / len(a)) / (sum(b) / len(b))


def fetch_boss_auras(client: WCLClient, con: sqlite3.Connection, encounter_id: int, difficulty: int,
                     boss_name: str, kills: int = 12,
                     log: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM aura_status a JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id FROM fight f LEFT JOIN aura_status a USING(report, fight_id) "
        f"WHERE {where} AND a.report IS NULL ORDER BY f.report LIMIT ?", (*params, max(0, kills - have))).fetchall()
    for r in todo:
        try:
            fr = client.query(FIGHT_QUERY, {"code": r[0], "f": [r[1]]},
                              cache_ttl=0)["reportData"]["report"]["fights"][0]
            s, e = fr["startTime"], fr["endTime"]
            rep = client.query(AURA_QUERY, {"code": r[0], "f": [r[1]], "s": s, "e": e},
                               cache_ttl=0)["reportData"]["report"]
        except (WCLError, KeyError, TypeError, IndexError, OSError) as ex:
            log(f"  auras skipped: {str(ex)[:100]}")
            continue
        actors = (rep.get("masterData") or {}).get("actors") or []
        boss_ids = {a["id"] for a in actors if a.get("name") == boss_name}
        enemy_ids = {a["id"] for a in actors}
        events = ((rep.get("debuffs") or {}).get("data") or []) + ((rep.get("buffs") or {}).get("data") or [])
        g = rep.get("graph") or {}
        g = g.get("data", g) if isinstance(g, dict) else {}
        series = next((x.get("data") or [] for x in g.get("series") or [] if x.get("name") == boss_name), [])
        step = (e - s) / 1000 / len(series) if series else 0
        rows = []
        for aid, ws in aura_windows(sorted(events, key=lambda x: x["timestamp"]), boss_ids, enemy_ids, s, e).items():
            ratio = rate_ratio(series, step, ws) if series else None
            rows += [(r[0], r[1], aid, "aura", round(t0, 1), round(d, 1), ratio) for t0, d in ws]
        con.executemany("INSERT INTO boss_aura VALUES(?,?,?,?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO aura_status VALUES(?,?)", (r[0], r[1]))
        con.commit()
    return len(todo)


def amp_candidates(con: sqlite3.Connection, encounter_id: int, difficulty: int, names: dict[int, str],
                   min_ratio: float = AMP_MIN_RATIO) -> list[tuple[str, float, list[tuple[float, float]], int, int]]:
    """Boss auras during which the boss takes damage faster in most kills: (name, median ratio, typical
    windows, kills seen, ability id). Suggestions for the boss notes, unless the game data confirms the amp."""
    from paf.corpus.analyze import canonical_waves

    where, params = kills_filter(encounter_id, difficulty)
    kills = con.execute(f"SELECT COUNT(*) FROM aura_status a JOIN fight f USING(report, fight_id) WHERE {where}",
                        params).fetchone()[0]
    by: dict[int, dict[tuple[str, int], list]] = {}
    for r in con.execute(f"SELECT b.* FROM boss_aura b JOIN fight f USING(report, fight_id) WHERE {where}", params):
        by.setdefault(r[2], {}).setdefault((r[0], r[1]), []).append((r[4], r[5], r[6]))
    out = []
    for aid, per_kill in by.items():
        if not kills or len(per_kill) < max(3, kills * 0.5):
            continue
        ratios = [x[2] for v in per_kill.values() for x in v if x[2] is not None]
        if not ratios or st.median(ratios) < min_ratio:
            continue
        waves = canonical_waves([[(t, 1, d, [""]) for t, d, _ in v] for v in per_kill.values()])
        wins = [(w.t, w.lifetime) for w in waves if w.lifetime >= 2]
        if wins:
            out.append((names.get(aid, f"spell {aid}"), round(st.median(ratios), 2), wins, len(per_kill), aid))
    return sorted(out, key=lambda x: -x[1])


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
