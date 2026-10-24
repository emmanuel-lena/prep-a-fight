"""Crafted items for the Gear tool (the owner, 2026-10-24: "the full package"): the crafted pieces the top players of
your spec wear, with their stats and embellishments (their bonus IDs) and at their item level, added to Top Gear's
candidates. A crafted item is one the game's crafting tables make (CraftingData). A set holds two embellished pieces
at most: two crafted items at most, yours counted (paf.topgear.build_combos)."""
from __future__ import annotations

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


def candidates(rows: list[dict], crafted: frozenset[int]) -> list[tuple[str, str, int, int]]:
    """(slot, simc value without the slot, item id, item level) of each crafted piece the top players wear: the most
    worn versions of each slot, its bonus IDs (stats, embellishment) and their item level kept."""
    if not rows or not crafted:
        return []
    n = len(rows)
    worn: Counter = Counter()
    level: dict[tuple, int] = {}
    for r in rows:
        for i, it in enumerate(r.get("gear") or []):
            if i in SLOTS and it.get("id") in crafted:
                key = (SLOTS[i].rstrip("12"), it["id"], tuple(it.get("bonusIDs") or []))
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
        out.append((slot, value, item, level[(fam, item, bonus)]))
    return out
