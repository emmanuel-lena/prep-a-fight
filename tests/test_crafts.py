from paf import crafts
from paf.profile import parse_simc_export
from paf.topgear import Gear, GearPool, build_combos


def row(**slots):
    gear = [{} for _ in range(17)]
    for i, it in slots.items():
        gear[int(i[1:])] = it
    return {"amount": 1, "gear": gear}


def test_the_crafted_candidates_are_the_top_players_with_their_stats_and_level():
    # the Gear tool (the owner, 2026-10-24): crafts as Raidbots sims them, from what the best players crafted
    cloak = {"id": 900, "bonusIDs": [1, 2], "itemLevel": 285}
    rows = [row(s14=cloak, s10={"id": 901, "bonusIDs": [3], "itemLevel": 285})] * 8 + [row(s14={"id": 77})] * 2
    got = crafts.candidates(rows, frozenset({900, 901}))
    assert ("back", ",id=900,bonus_id=1/2,ilevel=285", 900, 285) in got
    assert ("finger1", ",id=901,bonus_id=3,ilevel=285", 901, 285) in got and len(got) == 2  # a drop is no craft
    assert crafts.candidates(rows, frozenset()) == []  # offline: none


EXPORT = """rogue="T"
spec=subtlety
back=,id=10
finger1=,id=11
finger2=,id=12
neck=,id=13
"""


def test_a_set_holds_two_crafted_items_at_most():
    pool = GearPool(parse_simc_export(EXPORT), {}, {})
    a, b, c = (Gear(f"k{i}", f",id={i}", "", 285, "craft", i) for i in (900, 901, 902))
    kept = {"back": [a], "finger": [b], "neck": [c]}
    pool.candidates = [("back", a), ("finger1", b), ("neck", c)]
    combos = build_combos(pool, kept, crafted=frozenset({900, 901, 902}))
    worst = max(sum(g.item_id in {900, 901, 902} for o in c.options.values() for g in o.gears()) for c in combos)
    assert worst == 2 and len(combos) < len(build_combos(pool, kept))  # the 3-craft sets left out
