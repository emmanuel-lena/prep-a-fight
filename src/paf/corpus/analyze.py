"""First analyses of a boss corpus: fight shape, add waves, who hits adds, talents of the spec."""

from __future__ import annotations

import json
import sqlite3
import statistics as st
from collections import Counter, defaultdict
from dataclasses import dataclass, field

KILLABLE_DEATH_RATE = 0.5  # add types that die at least this often are "real" adds, the rest are mechanics
WAVE_GAP = 8.0  # seconds without a new spawn that close a wave within a kill
CLUSTER_GAP = 12.0  # seconds between wave starts that separate two canonical waves across kills
MIN_SUPPORT = 0.4  # a canonical wave must appear in at least 40% of the kills


def _q(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


@dataclass
class Wave:
    t: float  # median start (s)
    t_p25: float
    t_p75: float
    count: float  # median adds in the wave
    lifetime: float  # median lifetime (s)
    support: float  # share of kills where the wave exists
    types: list[str] = field(default_factory=list)


@dataclass
class Report:
    boss: str
    kills: int
    duration: tuple[float, float, float]  # p25, median, p75
    avg_ilvl: float
    phases: list[tuple[str, float, float, float]]  # name, p25, median, p75
    adds: list[tuple[str, float, float, float]]  # name, per kill, lifetime median, death rate
    waves: list[Wave]
    targets: list[tuple[str, float, bool]]  # target, damage share (all players), is a boss unit
    spec_add_share: list[tuple[str, int, float]]  # spec, players, median share of damage on adds
    ranked_add_share: tuple[float, float, float]  # p25/median/p75 for the analyzed spec's ranked players
    talents: list[tuple[str, float, float | None]]  # name, pick rate, add share delta (picked - not)


def main_boss(con: sqlite3.Connection, encounter_id: int, difficulty: int, default: str) -> str:
    """The boss unit that takes the most damage in the kills (an encounter is not always named after its
    boss: The Coiled Altar is Zul'jan, then Zul'jan and Hex Lord Malacrass)."""
    where, params = kills_filter(encounter_id, difficulty)
    row = con.execute(
        f"SELECT d.target, SUM(d.amount) AS s FROM damage_by_target d JOIN fight f USING(report, fight_id) "
        f"JOIN npc n ON n.name = d.target WHERE {where} AND n.is_boss = 1 GROUP BY d.target ORDER BY s DESC LIMIT 1",
        params).fetchone()
    return row[0] if row else default


FOCUS = "focus"  # cohort of the kills fetched only to measure rare specs (paf.raidneed): not the analyzed spec's


def kills_filter(encounter_id: int, difficulty: int, include_focus: bool = False) -> tuple[str, tuple]:
    if include_focus:
        return ("f.encounter_id=? AND f.difficulty=? AND f.status='done'", (encounter_id, difficulty))
    return ("f.encounter_id=? AND f.difficulty=? AND f.status='done' AND COALESCE(f.cohort, '') != 'focus'",
            (encounter_id, difficulty))


def fight_waves(spawns: list[tuple[float, float, str]]) -> list[tuple[float, int, float, list[str]]]:
    """Group one kill's add spawns (t_spawn, lifetime, type) into waves: (start, count, lifetime, types)."""
    waves: list[list[tuple[float, float, str]]] = []
    for s in sorted(spawns):
        if waves and s[0] - waves[-1][-1][0] <= WAVE_GAP:
            waves[-1].append(s)
        else:
            waves.append([s])
    return [(w[0][0], len(w), st.median(x[1] for x in w), sorted({x[2] for x in w})) for w in waves]


def canonical_waves(per_kill: list[list[tuple[float, int, float, list[str]]]]) -> list[Wave]:
    """Cluster wave starts across kills into the typical wave timeline of the boss."""
    n = len(per_kill)
    pts = sorted((w[0], k, w) for k, waves in enumerate(per_kill) for w in waves)
    clusters: list[list[tuple[float, int, tuple]]] = []
    for p in pts:
        if clusters and p[0] - clusters[-1][-1][0] <= CLUSTER_GAP:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    out: list[Wave] = []
    for c in clusters:
        by_kill: dict[int, list[tuple]] = defaultdict(list)
        for _, k, w in c:
            by_kill[k].append(w)
        support = len(by_kill) / n if n else 0
        if support < MIN_SUPPORT:
            continue
        starts = [min(w[0] for w in ws) for ws in by_kill.values()]
        counts = [sum(w[1] for w in ws) for ws in by_kill.values()]
        lifes = [st.median(w[2] for w in ws) for ws in by_kill.values()]
        types = Counter(t for ws in by_kill.values() for w in ws for t in w[3])
        out.append(Wave(round(st.median(starts), 1), round(_q(starts, .25), 1), round(_q(starts, .75), 1),
                        round(st.median(counts), 1), round(st.median(lifes), 1), round(support, 2),
                        [t for t, _ in types.most_common(3)]))
    return out


def analyze(con: sqlite3.Connection, encounter_id: int, difficulty: int, boss_name: str,
            spec: str, talent_names: dict[int, str] | None = None) -> Report:
    where, params = kills_filter(encounter_id, difficulty)
    fights = con.execute(f"SELECT report, fight_id, duration_s, avg_ilvl FROM fight f WHERE {where}",
                         params).fetchall()
    keys = {(r["report"], r["fight_id"]) for r in fights}
    durations = [r["duration_s"] for r in fights]

    phases: dict[str, list[float]] = defaultdict(list)
    order: dict[str, int] = {}
    for r in con.execute(f"SELECT p.* FROM phase p JOIN fight f USING(report, fight_id) WHERE {where}", params):
        phases[r["name"]].append(r["t_start"])
        order.setdefault(r["name"], r["phase_id"])
    phase_rows = [(nm, _q(v, .25), st.median(v), _q(v, .75)) for nm, v in sorted(phases.items(),
                                                                                  key=lambda kv: order[kv[0]])]

    add_rows = con.execute(
        f"SELECT a.report, a.fight_id, n.name, a.t_spawn, a.t_death, a.died FROM add_instance a "
        f"JOIN npc n USING(game_id) JOIN fight f USING(report, fight_id) WHERE {where}", params).fetchall()
    per_type: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in add_rows:
        per_type[r["name"]].append(r)
    adds = []
    killable = set()
    for name, rows in per_type.items():
        rate = sum(r["died"] for r in rows) / len(rows)
        life = st.median(r["t_death"] - r["t_spawn"] for r in rows if r["t_spawn"] is not None)
        adds.append((name, len(rows) / max(1, len(keys)), life, rate))
        if rate >= KILLABLE_DEATH_RATE:
            killable.add(name)
    adds.sort(key=lambda a: -a[1])

    spawns: dict[tuple[str, int], list[tuple[float, float, str]]] = defaultdict(list)
    for r in add_rows:
        if r["name"] in killable and r["t_spawn"] is not None:
            spawns[(r["report"], r["fight_id"])].append((r["t_spawn"], r["t_death"] - r["t_spawn"], r["name"]))
    waves = canonical_waves([fight_waves(spawns.get(k, [])) for k in sorted(keys)])

    dmg = con.execute(
        f"SELECT d.report, d.fight_id, d.actor_id, d.target, d.amount FROM damage_by_target d "
        f"JOIN fight f USING(report, fight_id) WHERE {where}", params).fetchall()
    boss_units = {r[0] for r in con.execute("SELECT name FROM npc WHERE is_boss=1")} | {boss_name}
    per_target: Counter[str] = Counter()
    per_player: dict[tuple[str, int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in dmg:
        per_target[r["target"]] += r["amount"] or 0
        acc = per_player[(r["report"], r["fight_id"], r["actor_id"])]
        acc[0] += r["amount"] or 0
        if r["target"] not in boss_units:
            acc[1] += r["amount"] or 0
    total = sum(per_target.values()) or 1
    targets = [(t, a / total, t in boss_units) for t, a in per_target.most_common(12)]

    specs: dict[str, list[float]] = defaultdict(list)
    for r in con.execute(f"SELECT p.* FROM player p JOIN fight f USING(report, fight_id) WHERE {where}", params):
        acc = per_player.get((r["report"], r["fight_id"], r["actor_id"]))
        if acc and acc[0] > 0:
            specs[f"{r['spec']} {r['class']}"].append(acc[1] / acc[0])
    spec_share = sorted(((s, len(v), st.median(v)) for s, v in specs.items() if len(v) >= 10),
                        key=lambda x: -x[2])

    ranked = con.execute(
        f"SELECT r.* FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} AND r.spec=?",
        (*params, spec)).fetchall()
    shares: dict[tuple[str, int], float] = {}
    for r in ranked:
        acc = per_player.get((r["report"], r["fight_id"], r["actor_id"]))
        if acc and acc[0] > 0:
            shares[(r["report"], r["fight_id"])] = acc[1] / acc[0]
    sv = list(shares.values())
    ranked_share = (_q(sv, .25), _q(sv, .5), _q(sv, .75)) if sv else (float("nan"),) * 3

    talents: list[tuple[str, float, float | None]] = []
    picks: dict[int, set[tuple[str, int]]] = defaultdict(set)
    for r in ranked:
        for t in json.loads(r["talents_json"] or "[]"):
            picks[t["talentID"]].add((r["report"], r["fight_id"]))
    n = len(ranked)
    names = talent_names or {}
    for tid, who in picks.items():
        rate = len(who) / n if n else 0
        delta = None
        with_t = [shares[k] for k in who if k in shares]
        without = [v for k, v in shares.items() if k not in who]
        if len(with_t) >= 5 and len(without) >= 5:
            delta = st.median(with_t) - st.median(without)
        talents.append((names.get(tid) or f"talent {tid}", rate, delta))
    talents.sort(key=lambda t: (-t[1], t[0]))

    return Report(boss_name, len(keys), (_q(durations, .25), st.median(durations) if durations else 0,
                                         _q(durations, .75)),
                  st.mean(r["avg_ilvl"] for r in fights if r["avg_ilvl"]) if fights else 0,
                  phase_rows, adds, waves, targets, spec_share, ranked_share, talents)


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def format_report(r: Report, spec: str, top_talents: int = 12) -> str:
    L: list[str] = []
    L.append(f"{r.boss}: {r.kills} kills, duration {_mmss(r.duration[1])} "
             f"(p25-p75 {_mmss(r.duration[0])}-{_mmss(r.duration[2])}), raid ilvl {r.avg_ilvl:.0f}")
    L.append("")
    L.append("Phases (start, median and p25-p75)")
    for nm, a, m, b in r.phases:
        L.append(f"  {_mmss(m):>5}  ({_mmss(a)}-{_mmss(b)})  {nm}")
    L.append("")
    L.append("Add waves (typical timeline across kills)")
    L.append("   start  (p25-p75)      adds  alive   seen in  types")
    for w in r.waves:
        L.append(f"  {_mmss(w.t):>5}  ({_mmss(w.t_p25)}-{_mmss(w.t_p75)})  {w.count:5.0f}  {w.lifetime:4.0f}s"
                 f"   {w.support:5.0%}   {', '.join(w.types)}")
    L.append("")
    L.append("Adds by type          per kill  lifetime  killed")
    for nm, per, life, rate in r.adds:
        tag = "" if rate >= KILLABLE_DEATH_RATE else "   (mechanic, not killed)"
        L.append(f"  {nm:<22} {per:6.1f}  {life:6.0f}s  {rate:6.0%}{tag}")
    L.append("")
    L.append("Damage done, by target (whole raid)")
    for t, s, is_boss in r.targets:
        L.append(f"  {s:6.1%}  {t}{'  (boss unit)' if is_boss else ''}")
    L.append("")
    L.append("Share of each spec's damage on adds, i.e. not on boss units (median)")
    for s, n, v in r.spec_add_share:
        mark = "  <-" if s.startswith(spec) else ""
        L.append(f"  {v:6.1%}  {s} ({n}){mark}")
    a, m, b = r.ranked_add_share
    L.append(f"  ranked {spec}: median {m:.1%} (p25-p75 {a:.1%}-{b:.1%})")
    L.append("")
    L.append(f"{spec} talents: pick rate among ranked players, and link with the share of damage on adds")
    varied = [t for t in r.talents if 0.1 <= t[1] <= 0.9]
    core = [t for t in r.talents if t[1] > 0.9]
    L.append(f"  {len(core)} talents taken by more than 90% of players (core build)")
    L.append("  choice talents (taken by 10-90%):")
    for nm, rate, delta in varied[:top_talents * 2]:
        d = f"{delta:+.1%} on adds" if delta is not None else ""
        L.append(f"    {rate:5.0%}  {nm:<32} {d}")
    return "\n".join(L)
