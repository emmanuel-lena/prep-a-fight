"""Crafted items for the Gear tool (the owner, 2026-10-24: "the full package"): the crafted pieces the top players of
your spec wear, with their stats and embellishments (their bonus IDs) and at their item level, added to Top Gear's
candidates. A crafted item is one the game's crafting tables make (CraftingData); its secondary stats are the missive
the top player chose, a bonus ID the logs carry (ItemBonus type 25). A set holds two embellished pieces at most: two
crafted items at most, yours counted (paf.topgear.build_combos)."""
from __future__ import annotations

import re
from collections import Counter
from functools import cache

from paf.specgear import SLOTS

SHARE = 0.10  # a candidate: worn by this share of the top players at least
PER_SLOT = 2


@cache
def crafted_ids() -> frozenset[int]:
    """Every item a profession crafts (empty offline: no crafted candidate)."""
    try:
        from paf.gamedata import table_rows

        ids = {int(r["CraftedItemID"]) for r in table_rows("CraftingData") if r.get("CraftedItemID", "0").isdigit()}
        ids |= {int(r["ItemID"]) for r in table_rows("CraftingDataItemQuality") if r.get("ItemID", "0").isdigit()}
    except Exception:  # noqa: BLE001
        return frozenset()
    return frozenset(i for i in ids if i)


STAT_NAMES = {32: "Crit", 36: "Haste", 40: "Versatility", 49: "Mastery"}


@cache
def missive_stats() -> dict[int, tuple[int, ...]]:
    """Bonus list id -> the secondary stats it sets (ItemBonus type 25): a missive's pair (Thalassian Missive of the
    Fireflash: 8790, Crit and Haste), read from the game data so each season's missives come with it."""
    try:
        from paf.gamedata import table_rows

        out: dict[int, list[int]] = {}
        for r in table_rows("ItemBonus"):
            if r.get("Type") == "25" and r.get("Value_0", "").isdigit():
                out.setdefault(int(r["ParentItemBonusListID"]), []).append(int(r["Value_0"]))
    except Exception:  # noqa: BLE001 - offline: no pair known
        return {}
    return {k: tuple(v) for k, v in out.items() if len(v) == 2}


def stats_of(bonus: tuple) -> tuple[int, ...] | None:
    """The missive pair among an item's bonus IDs (the top players' choice, in their logs), or None."""
    pairs = missive_stats()
    return next((pairs[int(b)] for b in bonus if str(b).isdigit() and int(b) in pairs), None)


def pairs() -> list[tuple[int, int]]:
    """Every missive pair of secondary stats the game knows (Crit/Haste, Crit/Mastery...), each once."""
    return sorted({tuple(sorted(p)) for p in missive_stats().values() if all(x in STAT_NAMES for x in p)})


def with_stats(value: str, pair: tuple[int, ...]) -> str:
    """An item's simc value with this missive pair (the bonus ID of another missive taken out)."""
    known = missive_stats()
    m = re.search(r",bonus_id=([\d/]+)", value)
    if m:
        kept = [b for b in m[1].split("/") if int(b) not in known]
        value = value.replace(m[0], ",bonus_id=" + "/".join(kept) if kept else "")
    value = re.sub(r",crafted_stats=[\d/]+", "", value)
    return f"{value},crafted_stats={'/'.join(str(x) for x in pair)}"


def candidates(rows: list[dict], crafted: frozenset[int]) -> list[tuple[str, str, int, int, tuple]]:
    """(slot, simc value without the slot, item id, item level, missive pair) of each crafted piece the top players
    wear, in every missive (the owner, 2026-10-24: "sim each missive to find the best gear on a fight"): the most worn
    pieces of each slot, their other bonus IDs (embellishment, sockets) and their item level kept."""
    if not rows or not crafted:
        return []
    n = len(rows)
    known = missive_stats()
    worn: Counter = Counter()
    level: dict[tuple, int] = {}
    for r in rows:
        for i, it in enumerate(r.get("gear") or []):
            if i in SLOTS and it.get("id") in crafted:
                bonus = tuple(b for b in it.get("bonusIDs") or [] if not (str(b).isdigit() and int(b) in known))
                key = (SLOTS[i].rstrip("12"), it["id"], bonus)  # one piece, whatever missive it was made with
                worn[key] += 1
                level[key] = max(level.get(key, 0), int(it.get("itemLevel") or 0))
    out = []
    per: Counter = Counter()
    for (fam, item, bonus), c in worn.most_common():
        if c / n < SHARE or per[fam] >= PER_SLOT:
            continue
        per[fam] += 1
        slot = {"finger": "finger1", "trinket": "trinket1"}.get(fam, fam)
        value = f",id={item}" + (",bonus_id=" + "/".join(str(b) for b in bonus) if bonus else "")
        if level[(fam, item, bonus)]:
            value += f",ilevel={level[(fam, item, bonus)]}"
        for pair in pairs() or [()]:
            out.append((slot, with_stats(value, pair) if pair else value, item, level[(fam, item, bonus)], pair))
    return out


def recrafts(line: str, crafted: frozenset[int]) -> list[tuple[str, tuple]]:
    """Your crafted piece remade with each other missive: (simc value, pair)."""
    m = re.search(r",id=(\d+)", line)
    if not m or int(m[1]) not in crafted:
        return []
    have = re.search(r"crafted_stats=(\d+)/(\d+)", line)
    mine = tuple(sorted((int(have[1]), int(have[2])))) if have else None
    return [(with_stats(line, p), p) for p in pairs() if p != mine]


def craftable(class_name: str, spec: str, crafted: frozenset[int]) -> list[tuple[str, int, str]]:
    """(slot, item id, name) of every piece this season's professions craft that your spec can use (your armor type,
    your weapons, your main stat): the Gear tool tries each, in every missive (the owner, 2026-10-24: "sim each slot
    with a craft too, really test everything")."""
    from paf.droptimizer import usable_loot
    from paf.gamedata import item_classes, item_names, item_primary, table_rows

    try:
        sparse = {int(r["ID"]): r for r in table_rows("ItemSparse") if r.get("ID", "").isdigit()
                  and int(r["ID"]) in crafted}
    except Exception:  # noqa: BLE001 - offline: none
        return []
    season = max((int(r.get("ExpansionID") or 0) for r in sparse.values()), default=0)
    ids = [i for i, r in sparse.items() if int(r.get("ExpansionID") or 0) == season
           and r.get("OverallQualityID") == "4"]  # epic: the gear tier of crafting, not the reagents' blues
    found = usable_loot([0], class_name, {0: ("craft", ids)}, item_classes(), item_names(), spec, item_primary())
    slot = {"finger": "finger1", "trinket": "trinket1", "two_hand": "main_hand"}
    return [(slot.get(x.slot, x.slot), x.item_id, sparse[x.item_id].get("Display_lang") or x.name) for x in found]
