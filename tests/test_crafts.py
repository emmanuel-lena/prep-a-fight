from paf import crafts
from paf.profile import parse_simc_export
from paf.topgear import Gear, GearPool, build_combos


def row(**slots):
    gear = [{} for _ in range(17)]
    for i, it in slots.items():
        gear[int(i[1:])] = it
    return {"amount": 1, "gear": gear}


def test_every_crafted_piece_is_tried_in_every_missive(monkeypatch):
    # the Gear tool (the owner, 2026-10-24: "sim each missive"): the top players' crafted pieces, their missive (a
    # bonus ID the logs carry: 8791 Crit/Mastery) taken out and each missive pair tried instead
    monkeypatch.setattr(crafts, "missive_stats", lambda: {8790: (32, 36), 8791: (32, 49)})
    assert crafts.stats_of(("12214", "8791")) == (32, 49) and crafts.stats_of((1, 2)) is None
    assert crafts.pairs() == [(32, 36), (32, 49)]
    cloak = {"id": 900, "bonusIDs": ["1", "8791"], "itemLevel": 285}
    other = {"id": 900, "bonusIDs": ["1", "8790"], "itemLevel": 285}  # the same cloak, another missive: one piece
    rows = [row(s14=cloak)] * 6 + [row(s14=other)] * 2 + [row(s14={"id": 77})] * 2
    got = crafts.candidates(rows, frozenset({900}))
    assert got == [("back", ",id=900,bonus_id=1,ilevel=285,crafted_stats=32/36", 900, 285, (32, 36)),
                   ("back", ",id=900,bonus_id=1,ilevel=285,crafted_stats=32/49", 900, 285, (32, 49))]
    assert crafts.candidates(rows, frozenset()) == []  # offline: none
    mine = "back=,id=900,bonus_id=1/8790,crafted_stats=32/36"
    assert crafts.recrafts(mine, frozenset({900})) == [("back=,id=900,bonus_id=1,crafted_stats=32/49", (32, 49))]


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
