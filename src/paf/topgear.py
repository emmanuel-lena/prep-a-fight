"""Top Gear: best combination of the items you own, per fight, with SimC profilesets.

Two passes, like the original PowerShell prototype:
1. every candidate item alone against the equipped set, on every fight profile; the best options per
   slot are kept;
2. every combination of the kept options (tier / great vault / unique / weapon rules), on every fight.
Results: best set per fight, weighted global ranking, and the regret of keeping one set everywhere.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from paf import simc
from paf.gamedata import (
    INV_HOLDABLE,
    INV_OFF_HAND,
    INV_RANGED,
    INV_RANGED_RIGHT,
    INV_SHIELD,
    INV_TWO_HAND,
)
from paf.profile import Item, Profile

ARMOR = ("head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet")
PAIRS = {"finger": ("finger1", "finger2"), "trinket": ("trinket1", "trinket2")}
ENCHANTABLE = {"head", "shoulder", "back", "chest", "wrist", "legs", "feet", "finger1", "finger2",
               "main_hand", "off_hand"}
TWO_HAND_TYPES = {INV_TWO_HAND, INV_RANGED, INV_RANGED_RIGHT}
OFF_HAND_TYPES = {INV_SHIELD, INV_OFF_HAND, INV_HOLDABLE}


def family(slot: str) -> str:
    for fam, slots in PAIRS.items():
        if slot in slots:
            return fam
    if slot in ("main_hand", "off_hand"):
        return "weapon"
    return slot


@dataclass(frozen=True)
class Gear:
    """One item as it would be equipped: its simc value (without the slot) and where it comes from."""
    key: str
    value: str
    name: str
    ilvl: int | None
    source: str  # equipped | bags | vault | linked
    item_id: int | None

    def label(self) -> str:
        ilvl = f" ({self.ilvl})" if self.ilvl else ""
        src = "" if self.source in ("equipped", "bags") else f" [{self.source}]"
        return f"{self.name or self.item_id}{ilvl}{src}"


@dataclass(frozen=True)
class Option:
    """What a family of slots becomes: {slot: Gear or None (empty slot)}."""
    fam: str
    slots: tuple[tuple[str, Gear | None], ...]

    def lines(self) -> list[str]:
        return [f"{s}={g.value if g else ''}" for s, g in self.slots]

    def gears(self) -> list[Gear]:
        return [g for _, g in self.slots if g]

    def label(self) -> str:
        return " + ".join(g.label() for g in self.gears()) or "(empty)"


@dataclass
class Combo:
    name: str
    options: dict[str, Option]  # only families that differ from the equipped set
    scores: dict[str, float] = field(default_factory=dict)  # fight -> delta % vs equipped
    errors: dict[str, float] = field(default_factory=dict)

    def weighted(self, weights: dict[str, float]) -> float:
        tot = sum(weights.values()) or 1
        return sum(self.scores.get(f, 0.0) * w for f, w in weights.items()) / tot


@dataclass
class FightProfile:
    name: str
    lines: list[str]
    weight: float = 1.0


def _with_enchant(value: str, equipped: Item | None) -> str:
    """Copy the enchant of the equipped item on a candidate that has none (like Raidbots)."""
    if not equipped or "enchant_id=" in value:
        return value
    ench = equipped.fields.get("enchant_id")
    return f"{value},enchant_id={ench}" if ench else value


class GearPool:
    def __init__(self, profile: Profile, inv_types: dict[int, int], sets: dict[int, tuple[int, str]]):
        self.profile = profile
        self.inv = inv_types
        self.sets = sets
        self.equipped: dict[str, Gear] = {}
        for slot, it in profile.equipped.items():
            self.equipped[slot] = Gear(f"eq:{slot}", it.line, it.name, it.ilvl, "equipped", it.item_id)
        self.candidates: list[tuple[str, Gear]] = []  # (slot as exported, gear)
        for n, it in enumerate(profile.candidates):
            if it.item_id is None:
                continue
            value = _with_enchant(it.line, profile.equipped.get(it.slot))
            self.candidates.append((it.slot, Gear(f"c{n}", value, it.name, it.ilvl, it.source, it.item_id)))
        ids = [g.item_id for g in self.equipped.values()]
        counts: dict[int, int] = {}
        for i in ids:
            if i in sets:
                counts[sets[i][0]] = counts.get(sets[i][0], 0) + 1
        self.tier_set = max(counts, key=counts.get) if counts and max(counts.values()) >= 2 else None

    def is_tier(self, g: Gear | None) -> bool:
        return bool(g and self.tier_set and self.sets.get(g.item_id or 0, (None,))[0] == self.tier_set)

    def two_handed(self, g: Gear | None) -> bool:
        return bool(g and self.inv.get(g.item_id or 0) in TWO_HAND_TYPES)

    def off_hand_item(self, g: Gear) -> bool:
        return self.inv.get(g.item_id or 0) in OFF_HAND_TYPES

    def equipped_option(self, fam: str) -> Option:
        if fam in PAIRS:
            return Option(fam, tuple((s, self.equipped.get(s)) for s in PAIRS[fam]))
        if fam == "weapon":
            return Option(fam, (("main_hand", self.equipped.get("main_hand")),
                                ("off_hand", self.equipped.get("off_hand"))))
        return Option(fam, ((fam, self.equipped.get(fam)),))

    def families(self) -> list[str]:
        fams = [s for s in ARMOR if s in self.equipped or any(c[0] == s for c in self.candidates)]
        return fams + [f for f in ("finger", "trinket", "weapon")]

    def single_swaps(self) -> list[tuple[Gear, Option]]:
        """Pass 1: each candidate alone (rings/trinkets in both slots)."""
        out: list[tuple[Gear, Option]] = []
        eq_mh, eq_oh = self.equipped.get("main_hand"), self.equipped.get("off_hand")
        for slot, g in self.candidates:
            fam = family(slot)
            if fam in PAIRS:
                a, b = PAIRS[fam]
                out.append((g, Option(fam, ((a, g), (b, self.equipped.get(b))))))
                out.append((g, Option(fam, ((a, self.equipped.get(a)), (b, g)))))
            elif fam == "weapon":
                if slot == "off_hand" or self.off_hand_item(g):
                    if eq_mh and not self.two_handed(eq_mh):
                        out.append((g, Option(fam, (("main_hand", eq_mh), ("off_hand", g)))))
                elif self.two_handed(g):
                    out.append((g, Option(fam, (("main_hand", g), ("off_hand", None)))))
                else:
                    out.append((g, Option(fam, (("main_hand", g), ("off_hand", eq_oh)))))
            else:
                out.append((g, Option(fam, ((slot, g),))))
        return out

    def options_for(self, fam: str, kept: list[Gear]) -> list[Option]:
        """Pass 2: every option of a family built from the equipped items and the kept candidates."""
        eq = self.equipped_option(fam)
        if fam in PAIRS:
            pool = [g for g in eq.gears()] + kept
            opts = []
            for a, b in itertools.combinations(pool, 2):
                if a.item_id == b.item_id:
                    continue  # unique-equipped
                opts.append(Option(fam, ((PAIRS[fam][0], a), (PAIRS[fam][1], b))))
            return opts or [eq]
        if fam == "weapon":
            mains = [g for g in [eq.slots[0][1]] + kept if g and not self.off_hand_item(g)]
            offs = [g for g in [eq.slots[1][1]] + kept if g and self.off_hand_item(g)]
            opts = []
            for m in dict.fromkeys(mains):
                if self.two_handed(m):
                    opts.append(Option(fam, (("main_hand", m), ("off_hand", None))))
                else:
                    for o in dict.fromkeys(offs) or [None]:
                        opts.append(Option(fam, (("main_hand", m), ("off_hand", o))))
            return opts or [eq]
        return [eq] + [Option(fam, ((fam, g),)) for g in kept]


def select_kept(pool: GearPool, pass1: dict[str, dict[str, float]], weights: dict[str, float],
                keep: dict[str, int], prune_below: float) -> dict[str, list[Gear]]:
    """Best candidates per family from pass 1 (score = weighted delta of the best slot placement)."""
    tot = sum(weights.values()) or 1
    best: dict[str, float] = {}
    for key, per_fight in pass1.items():
        score = sum(per_fight.get(f, 0.0) * w for f, w in weights.items()) / tot
        best[key] = max(best.get(key, float("-inf")), score)
    kept: dict[str, list[Gear]] = {}
    for slot, g in pool.candidates:
        fam = family(slot)
        if best.get(g.key, float("-inf")) >= prune_below:
            kept.setdefault(fam, []).append(g)
    for fam, gears in kept.items():
        gears.sort(key=lambda g: -best[g.key])
        n = keep.get(fam, keep.get("armor", 2))
        kept[fam] = list(dict.fromkeys(gears))[:n]
    return kept


def build_combos(pool: GearPool, kept: dict[str, list[Gear]], min_tier: int | None = None,
                 max_vault: int = 1, max_combos: int = 1500) -> list[Combo]:
    fams = pool.families()
    per_fam = {f: pool.options_for(f, kept.get(f, [])) for f in fams}
    equipped = {f: pool.equipped_option(f) for f in fams}
    eq_tier = sum(pool.is_tier(g) for g in pool.equipped.values())
    need_tier = min(eq_tier, 4) if min_tier is None else min_tier
    total = 1
    for opts in per_fam.values():
        total *= len(opts)
    if total > max_combos * 50:
        raise ValueError(f"{total} combinations before filtering: keep fewer items per slot")
    combos: list[Combo] = []
    for choice in itertools.product(*(per_fam[f] for f in fams)):
        gears = [g for o in choice for g in o.gears()]
        if sum(g.source == "vault" for g in gears) > max_vault:
            continue
        if sum(pool.is_tier(g) for g in gears) < need_tier:
            continue
        diff = {o.fam: o for o in choice if o != equipped[o.fam]}
        if not diff:
            continue
        combos.append(Combo(f"c{len(combos) + 1}", diff))
    return combos


@dataclass
class TopGearResult:
    fights: list[FightProfile]
    combos: list[Combo]
    run_dir: Path

    def best(self, fight: str | None = None) -> Combo | None:
        weights = {f.name: f.weight for f in self.fights}
        if not self.combos:
            return None
        if fight:
            return max(self.combos, key=lambda c: c.scores.get(fight, float("-inf")))
        return max(self.combos, key=lambda c: c.weighted(weights))


def score_of(res: simc.SimResult, ps: simc.ProfilesetResult, objective: float) -> float:
    """Delta % vs baseline; objective = weight of boss-only damage (0 = total damage, 1 = boss only)."""
    total = res.delta_pct(ps, "dps")
    if objective <= 0 or "prioritydps" not in res.baseline or "prioritydps" not in ps.metrics:
        return total
    boss = res.delta_pct(ps, "prioritydps")
    return objective * boss + (1 - objective) * total


def run_topgear(profile_text: str, pool: GearPool, fights: list[FightProfile], run_dir: Path, *,
                pass1_error: float = 0.3, pass2_error: float = 0.15, keep: dict[str, int] | None = None,
                prune_below: float = -0.5, min_tier: int | None = None, max_combos: int = 1500,
                objective: float = 0.0, log: Callable[[str], None] = print) -> TopGearResult:
    keep = keep or {"armor": 2, "finger": 3, "trinket": 3, "weapon": 3}
    weights = {f.name: f.weight for f in fights}
    swaps = pool.single_swaps()
    log(f"Pass 1: {len(swaps)} single swaps x {len(fights)} fight(s)")
    pass1: dict[str, dict[str, float]] = {}
    for fp in fights:
        sets = {f"s{i}": opt.lines() for i, (_, opt) in enumerate(swaps)}
        res = simc.run(simc.build_input(profile_text, fp.lines, sets), run_dir / f"pass1-{fp.name}",
                       target_error=pass1_error)
        by_name = {p.name: p for p in res.profilesets}
        for i, (g, _) in enumerate(swaps):
            ps = by_name.get(f"s{i}")
            if ps:
                d = score_of(res, ps, objective)
                cur = pass1.setdefault(g.key, {})
                cur[fp.name] = max(cur.get(fp.name, float("-inf")), d)
        log(f"  {fp.name}: {res.elapsed:.0f}s")

    kept = select_kept(pool, pass1, weights, keep, prune_below)

    def raw_count() -> int:
        n = 1
        for f in pool.families():
            n *= len(pool.options_for(f, kept.get(f, [])))
        return n

    def shrink() -> bool:
        # drop the weakest kept item of the family with the most options
        fams = [f for f in kept if kept[f]]
        if not fams:
            return False
        worst = max(fams, key=lambda f: len(pool.options_for(f, kept[f])))
        kept[worst] = kept[worst][:-1]
        return True

    while raw_count() > max_combos * 20 and shrink():
        pass
    combos = build_combos(pool, kept, min_tier=min_tier, max_combos=max_combos)
    while len(combos) > max_combos and shrink():
        combos = build_combos(pool, kept, min_tier=min_tier, max_combos=max_combos)
    log("  kept: " + "; ".join(f"{f}: {len(g)}" for f, g in kept.items() if g))
    log(f"Pass 2: {len(combos)} combinations x {len(fights)} fight(s)")
    for fp in fights:
        sets = {c.name: [line for o in c.options.values() for line in o.lines()] for c in combos}
        if not sets:
            break
        res = simc.run(simc.build_input(profile_text, fp.lines, sets), run_dir / f"pass2-{fp.name}",
                       target_error=pass2_error)
        by_name = {p.name: p for p in res.profilesets}
        for c in combos:
            ps = by_name.get(c.name)
            if ps:
                c.scores[fp.name] = score_of(res, ps, objective)
                c.errors[fp.name] = ps.dps.error / res.baseline["dps"].mean * 100 if res.baseline["dps"].mean else 0
        log(f"  {fp.name}: {res.elapsed:.0f}s")
    return TopGearResult(fights, combos, run_dir)


def format_result(r: TopGearResult, pool: GearPool, top: int = 10) -> str:
    weights = {f.name: f.weight for f in r.fights}
    names = [f.name for f in r.fights]
    L: list[str] = []
    if not r.combos:
        return "Nothing to compare: no candidate item in bags / vault / links."
    ranked = sorted(r.combos, key=lambda c: -c.weighted(weights))
    header = "  ".join(f"{n[:14]:>14}" for n in names)
    L.append(f"{'#':>3}  {'weighted':>8}  {header}  changes vs equipped")
    for i, c in enumerate(ranked[:top], 1):
        cols = "  ".join(f"{c.scores.get(n, float('nan')):+13.2f}%" for n in names)
        changes = "; ".join(f"{o.fam}: {o.label()}" for o in c.options.values())
        L.append(f"{i:>3}  {c.weighted(weights):+7.2f}%  {cols}  {changes}")
    L.append("")
    L.append("Best set per fight, and what you lose on it with the overall best set (regret)")
    glob = ranked[0]
    for n in names:
        b = max(r.combos, key=lambda c: c.scores.get(n, float("-inf")))
        regret = b.scores.get(n, 0) - glob.scores.get(n, 0)
        changes = "; ".join(f"{o.fam}: {o.label()}" for o in b.options.values())
        L.append(f"  {n}: {b.scores.get(n, 0):+.2f}% ({changes}); regret with the overall best: {regret:.2f}%")
    err = max((e for c in ranked[:top] for e in c.errors.values()), default=0)
    L.append("")
    L.append(f"Statistical error of each line: about +/-{err:.2f}%. Smaller differences are not significant.")
    return "\n".join(L)


def best_set_simc(pool: GearPool, combo: Combo) -> str:
    lines = []
    changed = {s: g for o in combo.options.values() for s, g in o.slots}
    for slot in [s for s in pool.profile.equipped] + [s for s in changed if s not in pool.profile.equipped]:
        g = changed.get(slot, pool.equipped.get(slot)) if slot in changed else pool.equipped.get(slot)
        if g is None:
            lines.append(f"{slot}=")
        else:
            lines.append(f"# {g.label()}\n{slot}={g.value}")
    return "\n".join(lines) + "\n"
