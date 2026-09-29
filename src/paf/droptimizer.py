"""Droptimizer: value of every item a boss can drop for your character, on the fights you choose.

Loot tables come from the Encounter Journal (wago.tools), so no hand-written loot list is needed.
Each item is simmed alone against the equipped set (rings and trinkets in both slots, best kept).
EV per boss = mean of the positive gains over its usable items (same definition as Raidbots).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from paf import simc
from paf.profile import Profile
from paf.topgear import FightProfile, score_of

CLASS_IDS = {"warrior": 1, "paladin": 2, "hunter": 3, "rogue": 4, "priest": 5, "deathknight": 6, "shaman": 7,
             "mage": 8, "warlock": 9, "monk": 10, "druid": 11, "demonhunter": 12, "evoker": 13}
# armor subclass worn by each class (1 cloth, 2 leather, 3 mail, 4 plate)
ARMOR_TYPE = {"warrior": 4, "paladin": 4, "deathknight": 4, "hunter": 3, "shaman": 3, "evoker": 3,
              "rogue": 2, "monk": 2, "druid": 2, "demonhunter": 2, "priest": 1, "mage": 1, "warlock": 1}
# weapon subclasses usable (2 = weapon class): 0 1H axe, 1 2H axe, 4 1H mace, 5 2H mace, 7 1H sword,
# 8 2H sword, 10 staff, 13 fist, 15 dagger, 6 polearm, 2 bow, 3 gun, 18 crossbow, 19 wand, 9 warglaive
WEAPONS = {
    "shaman": {0, 1, 4, 5, 10, 13, 15}, "priest": {4, 10, 15, 19}, "mage": {7, 10, 15, 19},
    "warlock": {7, 10, 15, 19}, "druid": {4, 5, 6, 10, 13, 15}, "evoker": {0, 1, 4, 5, 7, 8, 10, 13, 15},
    "paladin": {0, 1, 4, 5, 6, 7, 8}, "warrior": {0, 1, 4, 5, 6, 7, 8, 13, 15, 2, 3, 18},
    "deathknight": {0, 1, 4, 5, 6, 7, 8}, "hunter": {0, 1, 6, 7, 8, 10, 13, 15, 2, 3, 18},
    "rogue": {0, 4, 7, 13, 15}, "monk": {0, 4, 6, 7, 10, 13}, "demonhunter": {0, 7, 9, 13},
}
SHIELD_CLASSES = {"shaman", "paladin", "warrior"}
HOLDABLE_CLASSES = {"shaman", "priest", "mage", "warlock", "druid", "evoker", "monk", "paladin"}

INV_SLOT = {1: "head", 2: "neck", 3: "shoulder", 16: "back", 5: "chest", 20: "chest", 9: "wrist", 10: "hands",
            6: "waist", 7: "legs", 8: "feet", 11: "finger", 12: "trinket", 13: "main_hand", 21: "main_hand",
            17: "two_hand", 15: "two_hand", 26: "two_hand", 14: "off_hand", 22: "off_hand", 23: "off_hand"}
ARMOR_INV = {1, 3, 5, 20, 6, 7, 8, 9, 10}


@dataclass
class LootItem:
    item_id: int
    name: str
    slot: str  # head ... finger, trinket, main_hand, two_hand, off_hand
    boss: str
    deltas: dict[str, float] = field(default_factory=dict)  # fight -> best delta %
    error: float = 0.0

    def weighted(self, weights: dict[str, float]) -> float:
        tot = sum(weights.values()) or 1
        return sum(self.deltas.get(f, 0.0) * w for f, w in weights.items()) / tot


def usable_loot(encounters: list[int], class_name: str, loot: dict[int, tuple[str, list[int]]],
                classes: dict[int, tuple[int, int, int]], names: dict[int, tuple[str, int]]) -> list[LootItem]:
    cls = class_name.lower()
    bit = 1 << (CLASS_IDS.get(cls, 0) - 1) if cls in CLASS_IDS else -1
    out: list[LootItem] = []
    seen: set[int] = set()
    for enc in encounters:
        boss, items = loot.get(enc, ("", []))
        for iid in items:
            if iid in seen or iid not in classes:
                continue
            item_class, sub, inv = classes[iid]
            name, allow = names.get(iid, (str(iid), -1))
            if allow not in (-1, 0) and bit > 0 and not allow & bit:
                continue
            slot = INV_SLOT.get(inv)
            if slot is None:
                continue
            if item_class == 4 and inv in ARMOR_INV and sub != ARMOR_TYPE.get(cls):
                continue
            if item_class == 2 and sub not in WEAPONS.get(cls, set()):
                continue
            if inv == 14 and cls not in SHIELD_CLASSES:
                continue
            if inv == 23 and cls not in HOLDABLE_CLASSES:
                continue
            seen.add(iid)
            out.append(LootItem(iid, name, slot, boss))
    return out


def item_options(item: LootItem, profile: Profile, ilvl: int) -> list[list[str]]:
    """simc lines for each way of equipping the item (both ring/trinket slots)."""
    def value(slot: str) -> str:
        v = f",id={item.item_id},ilevel={ilvl}"
        eq = profile.equipped.get(slot)
        ench = eq.fields.get("enchant_id") if eq else None
        if ench and slot not in ("trinket1", "trinket2", "neck", "waist", "hands"):
            v += f",enchant_id={ench}"
        return v

    if item.slot == "finger":
        return [[f"finger1={value('finger1')}"], [f"finger2={value('finger2')}"]]
    if item.slot == "trinket":
        return [[f"trinket1={value('trinket1')}"], [f"trinket2={value('trinket2')}"]]
    if item.slot == "two_hand":
        return [[f"main_hand={value('main_hand')}", "off_hand="]]
    if item.slot == "main_hand":
        return [[f"main_hand={value('main_hand')}"]]
    return [[f"{item.slot}={value(item.slot)}"]]


def run_droptimizer(profile_text: str, profile: Profile, items: list[LootItem], fights: list[FightProfile],
                    run_dir: Path, ilvl: int, *, target_error: float = 0.2, objective: float = 0.0,
                    log: Callable[[str], None] = print) -> list[LootItem]:
    sets: dict[str, list[str]] = {}
    owner: dict[str, LootItem] = {}
    for n, it in enumerate(items):
        for k, lines in enumerate(item_options(it, profile, ilvl)):
            sets[f"i{n}_{k}"] = lines
            owner[f"i{n}_{k}"] = it
    log(f"{len(items)} items ({len(sets)} placements) x {len(fights)} fight(s) at item level {ilvl}")
    for fp in fights:
        res = simc.run(simc.build_input(profile_text, fp.lines, sets), run_dir / fp.name, target_error=target_error)
        base = res.baseline["dps"].mean or 1
        for ps in res.profilesets:
            it = owner.get(ps.name)
            if not it:
                continue
            d = score_of(res, ps, objective)
            if d > it.deltas.get(fp.name, float("-inf")):
                it.deltas[fp.name] = d
                it.error = max(it.error, ps.dps.error / base * 100)
        log(f"  {fp.name}: {res.elapsed:.0f}s")
    return items


def loot_in_best_sets(profile_text: str, profile: Profile, items: list[LootItem], base_sets: list[list[str]],
                      fight: FightProfile, run_dir: Path, ilvl: int, *, target_error: float = 0.2,
                      objective: float = 0.0) -> dict[int, float]:
    """Real value of each drop: the best of your top sets once the item is inserted in it, minus the best of
    those sets without it (the rest of the gear rearranged around the item, not a single swap on your
    equipped set). base_sets: gear lines of each base set, relative to the equipped set ([] = equipped)."""
    sets: dict[str, list[str]] = {}
    for b, lines in enumerate(base_sets):
        if lines:
            sets[f"b{b}"] = lines
        for n, it in enumerate(items):
            for k, opt in enumerate(item_options(it, profile, ilvl)):
                slots = {line.split("=", 1)[0] for line in opt}
                # the item replaces what the base set had in that slot; a 2H also empties the off-hand
                kept = [line for line in lines if line.split("=", 1)[0] not in slots]
                sets[f"b{b}_i{n}_{k}"] = kept + opt
    res = simc.run(simc.build_input(profile_text, fight.lines, sets), run_dir, target_error=target_error)
    by = {ps.name: score_of(res, ps, objective) for ps in res.profilesets}
    best_without = max([0.0] + [by.get(f"b{b}", float("-inf")) for b in range(len(base_sets)) if base_sets[b]])
    out = {}
    for n, it in enumerate(items):
        with_item = [v for name, v in by.items() if f"_i{n}_" in name]
        if with_item:
            out[it.item_id] = max(with_item) - best_without
    return out


def boss_ev(items: list[LootItem], weights: dict[str, float]) -> list[tuple[str, float, int]]:
    per: dict[str, list[float]] = {}
    for it in items:
        per.setdefault(it.boss, []).append(max(0.0, it.weighted(weights)))
    return sorted(((b, sum(v) / len(v), len(v)) for b, v in per.items()), key=lambda x: -x[1])
