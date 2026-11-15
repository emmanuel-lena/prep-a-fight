"""Your character in another spec of your class with your own items (issue #35): Top Gear on your /simc export's
bags, the items of that spec's main stat only, with the build paf.specgear found best for it. The top players' set at
334 (paf.specgear) says what a spec can do; this says what switching gives you with what you own."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from paf.specgear import ITEM_LINE, character_in, gear_lines, measured


@dataclass
class OwnGear:
    sim: float  # your character in that spec, in its best set from your items (the comparison's metric)
    error: float  # the sim's standard error, in % of its mean
    changes: list[str] = field(default_factory=list)  # the swaps from what you wear ("trinket: X (639)")
    missing: list[str] = field(default_factory=list)  # slots no item of yours fits (another main stat everywhere)
    weapon: str = ""  # a main-hand type SimC will not let this spec use some spells with ("Dagger" for Outlaw)
    lent: str = ""  # then the weapon simmed instead: the top players' main hand at your weapon's item level


WEAPON = re.compile(r"with invalid main-hand weapon type '([^']+)'")


def spec_text(profile: str, spec: str, talents: list[str]) -> str:
    """Your character as that spec, with these talents, wearing what you wear (the export's item lines)."""
    worn = [line.strip() for line in profile.splitlines() if ITEM_LINE.match(line.strip())]
    return character_in(profile, spec, talents, []).rstrip("\n") + "\n" + "\n".join(worn) + "\n"


def lend(text: str, weapons: list[dict], ilvl: int) -> tuple[str, dict[str, str]]:
    """Your character with the top players' weapons at your weapon's item level, in place of yours: a spec does not
    fight with another spec's weapon (your Subtlety daggers on an Outlaw, the owner: "sinon c'est nul")."""
    lines = gear_lines([{}] * 15 + list(weapons[:2]), ilvl)
    kept = [line for line in text.splitlines() if not re.match(r"(main_hand|off_hand)=", line.strip())]
    return "\n".join(kept + lines) + "\n", {line.partition("=")[0]: line.partition("=")[2] for line in lines}


def fits(item_id: int | None, want: str, primary: dict[int, set[str]]) -> bool:
    """An item that spec can use: no main stat (a ring, a trinket, a neck) or its main stat among the item's."""
    return not want or not item_id or not primary.get(item_id) or want in primary[item_id]


def refused(run_dir: Path) -> str:
    """The main-hand type SimC would not let the spec use some spells with, read in its log ("" when none)."""
    log_path = run_dir / "simc.log"
    found = WEAPON.search(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.is_file() else None
    return found[1] if found else ""


def own_gear(profile: str, cls: str, spec: str, talents: list[str], fight_lines: list[str], run_dir: Path, *,
             boss: bool = True, weapons: list[dict] | None = None, log=print) -> OwnGear | None:
    """Top Gear for that spec on your items (None: no /simc export with bags, nothing to choose from). `weapons`: the
    top players' main hand and off-hand, worn in place of yours when that spec refuses your main hand."""
    from paf import simc
    from paf.droptimizer import spec_primary
    from paf.gamedata import item_inventory_types, item_primary, item_sets
    from paf.profile import parse_simc_export
    from paf.topgear import FightProfile, Gear, GearPool, run_topgear

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
    base = simc.run(simc.build_input(text, fight_lines), run_dir / "worn")
    weapon, lent = refused(run_dir / "worn"), ""
    main = parsed.equipped.get("main_hand")
    if weapon and weapons and weapons[0].get("id") and main and main.ilvl:
        lent_text, values = lend(text, weapons, main.ilvl)
        try:
            base = simc.run(simc.build_input(lent_text, fight_lines), run_dir / "lent")
        except simc.SimcError as ex:  # their weapon too new for this SimC build: yours, said under the tile
            log(f"  the top players' weapon could not be simmed ({str(ex)[-80:]})")
        else:
            text = lent_text
            for slot in ("main_hand", "off_hand"):  # the lent weapons are what you wear, for Top Gear too
                pool.equipped.pop(slot, None)
            for n, (slot, value) in enumerate(values.items()):
                pool.equipped[slot] = Gear(f"eq:{slot}", value, weapons[n].get("name") or "", main.ilvl,
                                           "equipped", int(weapons[n]["id"]))
            wrong = [s for s in wrong if s not in values]
            lent = pool.equipped["main_hand"].label()
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
    value = measured(base.baseline.get("prioritydps"), base.baseline["dps"], boss)
    missing = [s for s in wrong if s not in slots]  # still another spec's main stat: said, never hidden
    return OwnGear(value * (1 + gain / 100), 100 * base.baseline["dps"].error / base.baseline["dps"].mean,
                   changes, missing, weapon, lent)
