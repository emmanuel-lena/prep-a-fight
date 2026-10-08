"""Who hits what in your raid: for each target the top raids cannot skip (a second boss, secondary boss units, adds),
the specs of your raid that do the most damage on it, and who should hit it, everyone in their own spec.

From the corpus of this boss (every player of the top kills, all specs; tanks, healers and the ranked player of the
corpus's spec left out), per kill:
- a player hits a target when they put on it at least half the raid's share of damage on it;
- a player is on a target (assigned) when they put on it at least 1.5 times the raid's share on it.
A target hit by 70% of the damage dealers or more is a whole-raid target; the number of players assigned to it
(possibly on top of the whole raid) is the median count of the kills. A target taking a quarter of the damage or more
is a second boss.
Each spec's DPS on a target: the median of its players assigned to it (an assigned target), on it and the main boss
together (a second boss: the specs that hit both), or on it (a whole-raid target).
In your pull: an assigned target gets the players of the specs that do the most damage on it, one target each; on a
whole-raid target, a player under half their spec's habit on it missed it.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import kills_filter
from paf.raidreview import MIN_SAMPLES, Target, _damage_spec

HITS = 0.5  # a player hits a target with this much of the raid's share on it
ON = 1.5  # a player is assigned to a target with this much of the raid's share on it
WHOLE_RAID = 0.7  # a target hit by this share of the damage dealers or more: the whole raid hits it
MIN_ASSIGNED = 2  # fewer players assigned in the top raids: nobody to assign
SECOND_BOSS = 0.25  # a target taking this share of the top raids' damage is a second boss
MISSED = 0.5  # on a whole-raid target, a player under this much of their spec's habit missed it
MIN_HABIT = 0.04
MIN_ON = 3  # kills where a spec was assigned to a target, to know its DPS there
SHOWN = 4  # specs shown per target
SWAP_GAIN = 0.05  # a spec change is shown when the other spec of the class does this much more boss damage


@dataclass
class Fit:
    habit: float  # median share of its players' damage on the target
    dps: float  # median DPS on the target (assigned target: of its players assigned to it; second boss: on both)


@dataclass
class TargetRef:
    name: str
    tops_share: float  # median share of the top raids' damage on it
    main_share: float  # and on the main boss
    players: int  # how many players are assigned to it in the top raids (median; 0 = nobody in particular)
    whole_raid: bool
    second_boss: bool
    fits: dict[str, Fit] = field(default_factory=dict)  # spec -> its fit on this target


@dataclass
class Assigned:
    target: str
    whole_raid: bool
    second_boss: bool
    players: int
    tops_share: float
    main_share: float
    raid_share: float  # your raid's share of damage on it in the pull
    ranking: list[tuple[str, float, list[str]]]  # your raid's specs, most damage on it first: (spec, DPS, players)
    proposed: list[tuple[str, str]]  # (name, spec)
    pulled: list[tuple[str, str, float]]  # who was on it in your pull: (name, spec, share of their damage)
    missed: list[tuple[str, str, float, float]] = field(default_factory=list)  # (name, spec, share, spec habit)


def references(con: sqlite3.Connection, encounter_id: int, difficulty: int, targets: list[Target]
               ) -> list[TargetRef]:
    where, params = kills_filter(encounter_id, difficulty, include_focus=True)
    dur = {(r[0], r[1]): r[2] for r in con.execute(f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}",
                                                   params)}
    specs = {(r[0], r[1], r[2]): f"{r[4]} {r[3]}" for r in con.execute(
        f"SELECT p.report, p.fight_id, p.actor_id, p.class, p.spec FROM player p JOIN fight f "
        f"USING(report, fight_id) WHERE {where}", params)}
    per: dict[tuple[str, int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for rep, fid, actor, target, amount in con.execute(
            f"SELECT d.report, d.fight_id, d.actor_id, d.target, d.amount FROM damage_by_target d "
            f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        per[(rep, fid, actor)][target] += amount or 0
    # the ranked player of each kill is a top player of the corpus's spec: left out, or that spec looks stronger
    ranked = {(r[0], r[1], r[2]) for r in con.execute(
        f"SELECT r.report, r.fight_id, r.actor_id FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where}",
        params)}
    kills: dict[tuple[str, int], list[tuple[str, dict[str, float]]]] = defaultdict(list)
    for key, totals in per.items():
        spec = specs.get(key)
        if spec and key not in ranked and _damage_spec(spec) and sum(totals.values()) > 0 and dur.get(key[:2]):
            kills[key[:2]].append((spec, totals))
    main = next((t for t in targets if t.main), None)
    out = []
    for t in targets:
        if t.main:
            continue
        second = t.tops_share >= SECOND_BOSS
        hit, on = [], []
        shares: dict[str, list[float]] = defaultdict(list)
        dps_all: dict[str, list[float]] = defaultdict(list)
        dps_on: dict[str, list[float]] = defaultdict(list)
        for kill, players in kills.items():
            d = dur[kill]
            raid = sum(x.get(t.name, 0.0) for _, x in players) / sum(sum(x.values()) for _, x in players)
            row = []
            for spec, totals in players:
                x = totals.get(t.name, 0.0) / sum(totals.values())
                on_it = totals.get(t.name, 0.0) + (totals.get(main.name, 0.0) if second and main else 0.0)
                shares[spec].append(x)
                dps_all[spec].append(on_it / d)
                row.append(x)
                if raid > 0 and x >= ON * raid:
                    dps_on[spec].append(on_it / d)
            if raid > 0:
                hit.append(sum(x >= HITS * raid for x in row) / len(row))
                on.append(sum(x >= ON * raid for x in row))
        if not hit:
            continue
        assigned = round(st.median(on))
        assigned = assigned if assigned >= MIN_ASSIGNED and not second else 0
        fits = {}
        for spec, vals in shares.items():
            if len(vals) < MIN_SAMPLES:
                continue
            ref = dps_on[spec] if assigned and len(dps_on[spec]) >= MIN_ON else dps_all[spec]
            fits[spec] = Fit(st.median(vals), st.median(ref))
        out.append(TargetRef(t.name, t.tops_share, main.tops_share if main else 0.0, assigned,
                             st.median(hit) >= WHOLE_RAID, second, fits))
    return out


def assign(rc, refs: list[TargetRef]) -> list[Assigned]:
    """rc: your raid's pull (paf.raidneed.raid_from_report)."""
    raid_tot = sum(sum(v.values()) for v in rc.targets.values()) or 1
    dealers = [(n, s, d) for n, s, d in rc.players if _damage_spec(s)]
    taken: set[str] = set()
    out = []
    for ref in sorted(refs, key=lambda r: (not r.second_boss, not r.players, -r.tops_share)):
        raid_share = sum(v.get(ref.name, 0.0) for v in rc.targets.values()) / raid_tot
        by_spec: dict[str, list[str]] = defaultdict(list)
        for name, spec, _ in sorted(dealers, key=lambda p: -p[2]):
            if spec in ref.fits:
                by_spec[spec].append(name)
        ranking = sorted(((s, ref.fits[s].dps, names) for s, names in by_spec.items()), key=lambda x: -x[1])
        pulled, missed = [], []
        for name, spec, _ in dealers:
            mine = rc.targets.get(name, {})
            share = mine.get(ref.name, 0.0) / (sum(mine.values()) or 1)
            fit = ref.fits.get(spec)
            if raid_share > 0 and share >= ON * raid_share:
                pulled.append((name, spec, share))
            elif ref.whole_raid and fit and fit.habit >= MIN_HABIT and share < MISSED * fit.habit:
                missed.append((name, spec, share, fit.habit))
        pulled.sort(key=lambda x: -x[2])
        proposed: list[tuple[str, str]] = []
        if ref.players:
            for spec, _, names in ranking:
                for name in names:
                    if len(proposed) < ref.players and name not in taken:
                        proposed.append((name, spec))
                        taken.add(name)
        out.append(Assigned(ref.name, ref.whole_raid, ref.second_boss, ref.players, ref.tops_share, ref.main_share,
                            raid_share, ranking, proposed, pulled, missed))
    return out


@dataclass
class Swap:
    name: str
    current: str
    better: str
    gain: float  # the better spec's boss DPS / the current spec's, minus 1 (medians of the top kills' players)


def boss_dps(con: sqlite3.Connection, encounter_id: int, difficulty: int, bosses: set[str]) -> dict[str, float]:
    """Spec -> median DPS of its players on the boss (and a second boss) in the top kills, the ranked player of the
    corpus's spec left out."""
    where, params = kills_filter(encounter_id, difficulty, include_focus=True)
    dur = {(r[0], r[1]): r[2] for r in con.execute(f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}",
                                                   params)}
    ranked = {(r[0], r[1], r[2]) for r in con.execute(
        f"SELECT r.report, r.fight_id, r.actor_id FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where}",
        params)}
    specs = {(r[0], r[1], r[2]): f"{r[4]} {r[3]}" for r in con.execute(
        f"SELECT p.report, p.fight_id, p.actor_id, p.class, p.spec FROM player p JOIN fight f "
        f"USING(report, fight_id) WHERE {where}", params)}
    on: dict[tuple[str, int, int], float] = defaultdict(float)
    for rep, fid, actor, target, amount in con.execute(
            f"SELECT d.report, d.fight_id, d.actor_id, d.target, d.amount FROM damage_by_target d "
            f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        on[(rep, fid, actor)] += (amount or 0) if target in bosses else 0.0
    per: dict[str, list[float]] = defaultdict(list)
    for key, spec in specs.items():
        if key not in ranked and _damage_spec(spec) and dur.get(key[:2]):
            per[spec].append(on.get(key, 0.0) / dur[key[:2]])
    return {s: st.median(v) for s, v in per.items() if len(v) >= MIN_SAMPLES}


def swaps(rc, dps: dict[str, float], class_specs: dict[str, list[str]]) -> list[Swap]:
    """The players of your pull whose class has a spec doing clearly more boss damage on this boss."""
    out = []
    for name, spec, _ in rc.players:
        if spec not in dps or not dps[spec]:
            continue
        others = [s for s in class_specs.get(spec.rpartition(" ")[2], []) if s != spec and s in dps]
        best = max(others, key=lambda s: dps[s], default=None)
        if best and dps[best] / dps[spec] - 1 >= SWAP_GAIN:
            out.append(Swap(name, spec, best, dps[best] / dps[spec] - 1))
    return sorted(out, key=lambda x: -x.gain)


def to_dict(boss: str, fight: str, rows: list[Assigned], swap_list: list[Swap] | None = None) -> dict:
    return {"boss": boss, "fight": fight,
            "swaps": [{"name": x.name, "current": x.current, "better": x.better, "gain": x.gain}
                      for x in swap_list or []],
            "targets": [
        {"name": a.target, "whole_raid": a.whole_raid, "second_boss": a.second_boss, "players": a.players,
         "tops": a.tops_share, "main": a.main_share, "raid": a.raid_share,
         "ranking": [{"spec": s, "dps": d, "players": n} for s, d, n in a.ranking[:SHOWN]],
         "proposed": [{"name": n, "spec": s} for n, s in a.proposed],
         "pulled": [{"name": n, "spec": s, "share": x} for n, s, x in a.pulled],
         "missed": [{"name": n, "spec": s, "share": x, "habit": h} for n, s, x, h in a.missed]} for a in rows]}
