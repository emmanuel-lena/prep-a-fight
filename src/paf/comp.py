"""Your raid's best comp on a boss: which spec each player brings (within their class) and who covers which target,
for the most boss damage while every target still gets the damage the top raids give it.

From the corpus of this boss (every player of the ranked kills, all specs):
- a spec's strength: the median DPS of its players;
- its habit on each target (the main boss, the secondary boss units, the adds): the median share of its damage there;
- its focus on a target: what its players who take that target the most put on it (90th percentile).
From your raid's pull: each player's skill = their DPS / the median DPS of the spec they played (a player at 90% of
the median is assumed at 90% on another spec of their class, capped at 130%).

Each target needs the top raids' weakest quarter of its share of the raid's damage. Everyone starts on the boss in
the spec of their class that does the most boss damage (a spec change only for 3% or more), leaking a third of their
spec's habit on the other targets (cleave). Then, while a target lacks damage, the cheapest move goes first: the
player and spec whose assignment on it costs the least boss damage per damage it brings there. Healers and tanks
stay as they are, with the damage they did in the pull.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import kills_filter
from paf.raidreview import MIN_SAMPLES, Target, _damage_spec

LOW_Q = 0.25  # what a player focusing the boss still puts on a target: this quantile of the spec's shares there
FOCUS_Q = 0.9  # what a player assigned to a target puts on it: this quantile of the spec's shares there
MAX_SKILL = 1.3
ASSIGN_COST = 0.03  # an assignment costs this share of the player's damage (fewer, bigger assignments first)
SWAP_MIN = 0.03  # a spec change for boss damage only when it brings at least this much more


@dataclass
class SpecStat:
    spec: str
    dps: float  # median DPS of its players on this boss
    habit: dict[str, float]  # target -> median share of its damage
    focus: dict[str, float]  # target -> share of the players who take it the most
    low: dict[str, float]  # target -> share of the players who take it the least (still forced on it)
    samples: int


@dataclass
class Pick:
    name: str
    current: str  # spec played in the pull
    spec: str  # spec proposed
    job: str  # the main boss's name, or the target they cover
    damage: dict[str, float]  # target -> estimated DPS on it
    role: str = "damage"  # damage | healer | tank | unknown

    @property
    def boss(self) -> float:
        return self.damage.get("__main__", 0.0)


@dataclass
class Comp:
    boss_name: str
    picks: list[Pick]
    need: dict[str, float]  # target -> DPS it needs
    got: dict[str, float]  # target -> DPS it gets with this comp
    boss: float  # estimated boss DPS of the proposal
    baseline: float  # the same players in their specs, playing like the top players of their spec
    pulled: float  # boss DPS in the pull
    notes: list[str] = field(default_factory=list)

    @property
    def gain(self) -> float:
        return self.boss / self.baseline - 1 if self.baseline else 0.0


def spec_stats(con: sqlite3.Connection, encounter_id: int, difficulty: int, targets: list[str]
               ) -> dict[str, SpecStat]:
    where, params = kills_filter(encounter_id, difficulty, include_focus=True)
    dur = {(r[0], r[1]): r[2] for r in con.execute(
        f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}", params)}
    specs = {(r[0], r[1], r[2]): f"{r[4]} {r[3]}" for r in con.execute(
        f"SELECT p.report, p.fight_id, p.actor_id, p.class, p.spec FROM player p JOIN fight f "
        f"USING(report, fight_id) WHERE {where}", params)}
    per: dict[tuple[str, int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for rep, fid, actor, target, amount in con.execute(
            f"SELECT d.report, d.fight_id, d.actor_id, d.target, d.amount FROM damage_by_target d "
            f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        per[(rep, fid, actor)][target] += amount or 0
    dps: dict[str, list[float]] = defaultdict(list)
    shares: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for key, totals in per.items():
        spec, d = specs.get(key), dur.get(key[:2])
        tot = sum(totals.values())
        if not spec or not d or tot <= 0:
            continue
        dps[spec].append(tot / d)
        for t in targets:
            shares[spec][t].append(totals.get(t, 0.0) / tot)
    out = {}
    for spec, vals in dps.items():
        if len(vals) < MIN_SAMPLES:
            continue
        habit = {t: st.median(v) for t, v in shares[spec].items()}
        focus = {t: _q(v, FOCUS_Q) for t, v in shares[spec].items()}
        low = {t: _q(v, LOW_Q) for t, v in shares[spec].items()}
        out[spec] = SpecStat(spec, st.median(vals), habit, focus, low, len(vals))
    return out


def _q(values: list[float], q: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * q))]


def class_of(spec: str) -> str:
    return spec.rpartition(" ")[2]


def _damage(total: float, s: SpecStat, job: str, main: str, others: list[str]) -> dict[str, float]:
    """DPS on each target ("__main__" = the boss) for a player of this spec doing `job`."""
    out = {}
    for t in others:
        share = s.focus.get(t, 0.0) if t == job else s.low.get(t, 0.0)
        out[t] = total * share
    used = sum(out.values())
    if used > total:  # cannot put more than all of it elsewhere
        out = {t: v * total / used for t, v in out.items()}
        used = total
    out["__main__"] = total - used
    return out


def _habit_damage(total: float, s: SpecStat, others: list[str]) -> dict[str, float]:
    out = {t: total * s.habit.get(t, 0.0) for t in others}
    out["__main__"] = total - sum(out.values())
    return out


def propose(rc, targets: list[Target], stats: dict[str, SpecStat], class_specs: dict[str, list[str]]) -> Comp:
    """rc: your raid's pull (paf.raidneed.raid_from_report). class_specs: class -> its damage specs."""
    main = next((t.name for t in targets if t.main), "")
    others = [t.name for t in targets if not t.main]
    raid_total = sum(d for _, _, d in rc.players)
    need = {t.name: t.tops_low * raid_total for t in targets if not t.main}
    fixed: list[Pick] = []
    options: dict[str, list[Pick]] = {}
    chosen: dict[str, Pick] = {}
    baseline = 0.0
    for name, spec, dps in rc.players:
        cur = stats.get(spec)
        if not _damage_spec(spec) or cur is None:
            # healers, tanks, specs not measured: what they did in the pull
            dur = rc.duration or 1
            done = rc.targets.get(name, {})
            dmg = {t: done.get(t, 0.0) / dur for t in others}
            dmg["__main__"] = done.get(main, 0.0) / dur
            role = "damage" if _damage_spec(spec) else "support"
            fixed.append(Pick(name, spec, spec, main, dmg, role if role == "support" else "unknown"))
            baseline += dmg["__main__"]
            continue
        skill = min(MAX_SKILL, dps / cur.dps) if cur.dps else 1.0
        baseline += _habit_damage(dps, cur, others)["__main__"]
        opts = []
        for s in [spec] + [x for x in class_specs.get(class_of(spec), []) if x != spec and x in stats]:
            total = skill * stats[s].dps if s != spec else dps
            for job in [main] + others:
                opts.append(Pick(name, spec, s, job, _damage(total, stats[s], job, main, others)))
        options[name] = opts
        on_boss = [o for o in opts if o.job == main]
        stay = next(o for o in on_boss if o.spec == spec)
        best = max(on_boss, key=lambda o: o.boss)
        chosen[name] = best if best.boss >= stay.boss * (1 + SWAP_MIN) else stay

    def got() -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for p in fixed + list(chosen.values()):
            for t, v in p.damage.items():
                out[t] += v
        return out

    def deficit(g: dict[str, float]) -> float:
        return sum(max(0.0, need[t] - g.get(t, 0.0)) for t in need)

    g = got()
    while deficit(g) > 0:
        best, best_cost = None, None
        for name, opts in options.items():
            cur = chosen[name]
            for o in opts:
                if o is cur:
                    continue
                g2 = {t: g.get(t, 0.0) - cur.damage.get(t, 0.0) + o.damage.get(t, 0.0) for t in set(g) | set(o.damage)}
                helped = deficit(g) - deficit(g2)
                if helped <= 1e-6:
                    continue
                extra = ASSIGN_COST * sum(o.damage.values()) if o.job != main and cur.job == main else 0.0
                cost = (cur.boss - o.boss + extra) / helped
                if best_cost is None or cost < best_cost:
                    best, best_cost = o, cost
        if best is None:
            break
        chosen[best.name] = best
        g = got()
    notes = [f"Even with the best moves, {t} stays under the top raids' damage on it." for t in need
             if g.get(t, 0.0) < need[t] - 1]
    if any(p.role == "unknown" for p in fixed):
        notes.append("Some specs are not measured on this boss yet: they are kept as they played.")
    picks = list(chosen.values()) + fixed
    pulled = sum(rc.targets.get(n, {}).get(main, 0.0) for n, _, _ in rc.players) / (rc.duration or 1)
    return Comp(main, picks, need, {t: g.get(t, 0.0) for t in need}, g.get("__main__", 0.0), baseline, pulled, notes)


def to_dict(c: Comp) -> dict:
    order = {"damage": 0, "unknown": 1, "support": 2}
    picks = sorted(c.picks, key=lambda p: (order[p.role], p.job == c.boss_name, p.spec == p.current, -p.boss))
    return {"boss": c.boss_name, "gain": c.gain, "boss_dps": c.boss, "baseline": c.baseline, "pulled": c.pulled,
            "targets": [{"name": t, "need": c.need[t], "got": c.got[t]} for t in c.need],
            "picks": [{"name": p.name, "current": p.current, "spec": p.spec, "job": p.job, "role": p.role,
                       "boss": p.boss, "on_job": p.damage.get(p.job, 0.0) if p.job != c.boss_name else p.boss}
                      for p in picks],
            "notes": c.notes}
