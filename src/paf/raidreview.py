"""Who does what in your raid's pull, next to the top raids (boss damage first).

For every target that matters on this boss (the main boss, the secondary boss units like Drowned Echo or Echo of
Jawae, the adds the top raids kill), the corpus gives:
- each spec's habit: the median share of its damage on that target in the top kills (whole fight);
- the top raids' share of their damage on that target (median and weakest quarter).
Your raid's pull gives the same for each player and for the raid. Then, boss damage first:
- a target your raid covers less than the top raids' weakest quarter needs more: the players whose spec takes it the
  most in the top kills are asked to go on it;
- a target your raid already covers: the players who put much more on it than the top players of their spec can
  move that damage to the boss.
This compares habits; it does not know your raid's assignments (a soak, a kick): the page says so.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import kills_filter

MIN_SHARE = 0.02  # a target must take this share of the top raids' damage to matter
MIN_SAMPLES = 8  # kills of a spec to know its habit
SHORT = 0.01  # a target is short when the raid is this far (share of its damage) under the top raids' weakest quarter
OVER = 0.08  # a player putting this much more than the top players of their spec on a covered target
NON_DAMAGE = ("Restoration", "Holy", "Discipline", "Mistweaver", "Preservation", "Blood", "Brewmaster", "Guardian",
              "Protection", "Vengeance")


@dataclass
class Target:
    name: str
    main: bool
    tops_share: float  # median share of the top raids' damage on it
    tops_low: float  # their weakest quarter
    raid_share: float = 0.0  # your raid's share on it

    @property
    def covered(self) -> bool:
        return self.main or self.raid_share >= self.tops_low - SHORT


@dataclass
class PlayerReview:
    name: str
    spec: str
    dps: float
    shares: dict[str, float]  # target -> share of their damage
    habit: dict[str, float]  # target -> median share of the top players of the spec (missing: unknown)
    verdict: str = "ok"  # ok | to_target | to_boss | unknown
    target: str = ""  # the target the verdict is about
    moved: float = 0.0  # share of their damage the verdict moves


@dataclass
class RaidReview:
    boss: str
    fight: str
    targets: list[Target]
    players: list[PlayerReview] = field(default_factory=list)


def _damage_spec(spec: str) -> bool:
    if "icon" in spec.lower() or " " not in spec:  # not a "Spec Class" (a custom icon in the log)
        return False
    return not any(spec.startswith(x + " ") for x in NON_DAMAGE)


def references(con: sqlite3.Connection, encounter_id: int, difficulty: int, main: str
               ) -> tuple[list[Target], dict[str, dict[str, float]]]:
    """The targets that matter, with the top raids' shares, and each spec's habit on them."""
    where, params = kills_filter(encounter_id, difficulty, include_focus=True)
    raid: dict[tuple[str, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    per_player: dict[tuple[str, int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for rep, fid, actor, target, amount in con.execute(
            f"SELECT d.report, d.fight_id, d.actor_id, d.target, d.amount FROM damage_by_target d "
            f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        raid[(rep, fid)][target] += amount or 0
        per_player[(rep, fid, actor)][target] += amount or 0
    if not raid:
        return [], {}
    shares: dict[str, list[float]] = defaultdict(list)
    for totals in raid.values():
        tot = sum(totals.values()) or 1
        for name, v in totals.items():
            shares[name].append(v / tot)
    kills = len(raid)
    targets = []
    for name, vals in shares.items():
        vals += [0.0] * (kills - len(vals))  # kills where nobody hit it
        med = st.median(vals)
        if name == main or med >= MIN_SHARE:
            ordered = sorted(vals)
            targets.append(Target(name, name == main, med, ordered[len(ordered) // 4]))
    names = {t.name for t in targets}
    specs: dict[tuple[str, int, int], str] = {
        (r[0], r[1], r[2]): f"{r[4]} {r[3]}" for r in con.execute(
            f"SELECT p.report, p.fight_id, p.actor_id, p.class, p.spec FROM player p JOIN fight f "
            f"USING(report, fight_id) WHERE {where}", params)}
    habit: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for key, totals in per_player.items():
        spec = specs.get(key)
        tot = sum(totals.values())
        if not spec or tot <= 0:
            continue
        for name in names:
            habit[spec][name].append(totals.get(name, 0.0) / tot)
    out = {spec: {n: st.median(v) for n, v in per.items() if len(v) >= MIN_SAMPLES} for spec, per in habit.items()}
    return sorted(targets, key=lambda t: (not t.main, -t.tops_share)), out


def review(rc, targets: list[Target], habits: dict[str, dict[str, float]], boss: str) -> RaidReview:
    """rc: your raid's pull (paf.raidneed.raid_from_report)."""
    names = {t.name for t in targets}
    raid_tot = sum(sum(v.values()) for v in rc.targets.values()) or 1
    by_target = {t.name: t for t in targets}
    for t in targets:
        t.raid_share = sum(v.get(t.name, 0.0) for v in rc.targets.values()) / raid_tot
    main = next((t.name for t in targets if t.main), boss)
    players = []
    for name, spec, dps in rc.players:
        if not _damage_spec(spec):
            continue
        totals = rc.targets.get(name, {})
        tot = sum(totals.values()) or 1
        shares = {n: totals.get(n, 0.0) / tot for n in names}
        players.append(PlayerReview(name, spec, dps, shares, habits.get(spec, {})))
    # boss damage first: a target under the top raids' weakest quarter gets the players whose spec takes it most
    for t in targets:
        if t.covered:
            continue
        needed = (t.tops_low - t.raid_share) * raid_tot  # damage missing on it
        ranked = sorted((p for p in players if t.name in p.habit and p.verdict == "ok"),
                        key=lambda p: -(p.habit[t.name] - p.shares.get(t.name, 0.0)) * p.dps)
        for p in ranked:
            if needed <= 0:
                break
            gap = p.habit[t.name] - p.shares.get(t.name, 0.0)
            if gap <= 0.02:
                continue
            p.verdict, p.target, p.moved = "to_target", t.name, gap
            needed -= gap * p.dps * rc.duration
    # covered targets: much more than the top players of the spec on them -> back to the boss
    for p in players:
        if p.verdict != "ok":
            continue
        if not p.habit:
            p.verdict = "unknown"
            continue
        extra = [(n, p.shares.get(n, 0.0) - p.habit.get(n, 0.0)) for n in names
                 if n != main and by_target[n].covered and n in p.habit]
        n, over = max(extra, key=lambda x: x[1], default=("", 0.0))
        if over >= OVER:
            p.verdict, p.target, p.moved = "to_boss", n, over
    order = {"to_target": 0, "to_boss": 1, "ok": 2, "unknown": 3}
    return RaidReview(boss, rc.fight, targets, sorted(players, key=lambda p: (order[p.verdict], -p.dps)))


def to_dict(r: RaidReview) -> dict:
    return {"boss": r.boss, "fight": r.fight,
            "targets": [{"name": t.name, "main": t.main, "tops": t.tops_share, "low": t.tops_low,
                         "raid": t.raid_share, "covered": t.covered} for t in r.targets],
            "players": [{"name": p.name, "spec": p.spec, "dps": p.dps, "shares": p.shares, "habit": p.habit,
                         "verdict": p.verdict, "target": p.target, "moved": p.moved} for p in r.players]}
