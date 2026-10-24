"""Your character in another spec of your class with your own items (issue #35): Top Gear on your /simc export's
bags, the items of that spec's main stat only, with the build paf.specgear found best for it. The top players' set at
334 (paf.specgear) says what a spec can do; this says what switching gives you with what you own."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paf.specgear import ITEM_LINE, character_in, measured


@dataclass
class OwnGear:
    sim: float  # your character in that spec, in its best set from your items (the comparison's metric)
    error: float  # the sim's standard error, in % of its mean
    changes: list[str] = field(default_factory=list)  # the swaps from what you wear ("trinket: X (639)")
    missing: list[str] = field(default_factory=list)  # slots no item of yours fits (another main stat everywhere)


def spec_text(profile: str, spec: str, talents: list[str]) -> str:
    """Your character as that spec, with these talents, wearing what you wear (the export's item lines)."""
    worn = [line.strip() for line in profile.splitlines() if ITEM_LINE.match(line.strip())]
    return character_in(profile, spec, talents, []).rstrip("\n") + "\n" + "\n".join(worn) + "\n"


def fits(item_id: int | None, want: str, primary: dict[int, set[str]]) -> bool:
    """An item that spec can use: no main stat (a ring, a trinket, a neck) or its main stat among the item's."""
    return not want or not item_id or not primary.get(item_id) or want in primary[item_id]


def own_gear(profile: str, cls: str, spec: str, talents: list[str], fight_lines: list[str], run_dir: Path, *,
             boss: bool = True, log=print) -> OwnGear | None:
    """Top Gear for that spec on your items (None: no /simc export with bags, nothing to choose from)."""
    from paf import simc
    from paf.droptimizer import spec_primary
    from paf.gamedata import item_inventory_types, item_primary, item_sets
    from paf.profile import parse_simc_export
    from paf.topgear import FightProfile, GearPool, run_topgear

    text = spec_text(profile, spec, talents)
    parsed = parse_simc_export(profile)
    try:
        primary = item_primary()
    except Exception:  # noqa: BLE001 - offline: every item kept, the sim weighs a wrong stat as nothing
        primary = {}
    want = spec_primary(cls, spec)
    pool = GearPool(parsed, item_inventory_types(), item_sets())
    pool.candidates = [(slot, g) for slot, g in pool.candidates if fits(g.item_id, want, primary)]
    wrong = sorted({slot for slot, it in parsed.equipped.items() if not fits(it.item_id, want, primary)})
    fight = [FightProfile("boss fight", fight_lines)]
    gain, changes, slots = 0.0, [], set()
    if pool.candidates:
        res = run_topgear(text, pool, fight, run_dir / "topgear", objective=1.0 if boss else 0.0, max_combos=200,
                          pass1_error=0.5, pass2_error=0.3, log=lambda m: None)
        best = res.best()
        if best is not None and best.weighted({"boss fight": 1.0}) > 0:
            gain = best.weighted({"boss fight": 1.0})
            changes = [f"{o.fam}: {o.label()}" for o in best.options.values()]
            slots = {slot for o in best.options.values() for slot, g in o.slots  # replaced, not kept beside
                     if g is None or pool.equipped.get(slot) is None or g.key != pool.equipped[slot].key}
    base = simc.run(simc.build_input(text, fight_lines), run_dir / "worn")
    value = measured(base.baseline.get("prioritydps"), base.baseline["dps"], boss)
    missing = [s for s in wrong if s not in slots]  # still another spec's main stat: said, never hidden
    return OwnGear(value * (1 + gain / 100), 100 * base.baseline["dps"].error / base.baseline["dps"].mean,
                   changes, missing)
