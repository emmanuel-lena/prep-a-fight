from paf.profile import parse_simc_export
from paf.topgear import GearPool, build_combos, select_kept

EXPORT = """shaman="T"
spec=elemental
# Tier Helm (321)
head=,id=1001,enchant_id=50
# Tier Shoulders (321)
shoulder=,id=1002
# Tier Hands (321)
hands=,id=1003
# Tier Legs (321)
legs=,id=1004
chest=,id=2000,enchant_id=60
finger1=,id=3001
finger2=,id=3002
trinket1=,id=4001
trinket2=,id=4002
main_hand=,id=5001
off_hand=,id=5002

### Gear from Bags
#
# Other Helm (330)
# head=,id=2001
#
# Tier Chest (321)
# chest=,id=1005
#
# Ring A (321)
# finger1=,id=3003
#
# Staff (330)
# main_hand=,id=5003
#
# Shield B (330)
# off_hand=,id=5004

### Weekly Reward Choices
#
# Vault Trinket (330)
# trinket1=,id=4003
#
# Vault Ring (330)
# finger1=,id=3004
### End of Weekly Reward Choices
"""

INV = {5001: 13, 5002: 14, 5003: 17, 5004: 14}
SETS = {i: (77, "Tier") for i in (1001, 1002, 1003, 1004, 1005)}


def pool():
    return GearPool(parse_simc_export(EXPORT), INV, SETS)


def test_pool_basics():
    p = pool()
    assert p.tier_set == 77
    assert len(p.candidates) == 7
    helm = next(g for s, g in p.candidates if g.item_id == 2001)
    assert "enchant_id=50" in helm.value  # enchant copied from the equipped helm
    assert p.two_handed(next(g for s, g in p.candidates if g.item_id == 5003))


def test_single_swaps():
    swaps = pool().single_swaps()
    by_item: dict = {}
    for g, opt in swaps:
        by_item.setdefault(g.item_id, []).append(opt)
    assert len(by_item[3003]) == 2  # a ring is tried in both slots
    staff = by_item[5003][0]
    assert staff.lines() == ["main_hand=,id=5003", "off_hand="]  # 2H empties the off-hand
    shield = by_item[5004][0]
    assert shield.lines() == ["main_hand=,id=5001", "off_hand=,id=5004"]


def test_combos_respect_rules():
    p = pool()
    kept = {family: [g for s, g in p.candidates if s.startswith(prefix)]
            for family, prefix in (("head", "head"), ("chest", "chest"), ("finger", "finger"),
                                   ("trinket", "trinket"), ("weapon", ""))}
    kept["weapon"] = [g for s, g in p.candidates if s in ("main_hand", "off_hand")]
    combos = build_combos(p, kept)
    assert combos
    for c in combos:
        gears = [g for o in c.options.values() for g in o.gears()]
        assert sum(g.source == "vault" for g in gears) <= 1
        eq_tier = {"head": 1001, "shoulder": 1002, "hands": 1003, "legs": 1004, "chest": 2000}
        tier = 0
        for slot, item in eq_tier.items():
            fam_opt = c.options.get(slot)
            gid = fam_opt.slots[0][1].item_id if fam_opt else item
            tier += gid in SETS
        assert tier >= 4
        if "finger" in c.options:
            ids = [g.item_id for g in c.options["finger"].gears()]
            assert len(set(ids)) == 2
    # vault ring + vault trinket together is never proposed
    assert not any({g.item_id for o in c.options.values() for g in o.gears()} >= {3004, 4003} for c in combos)


def test_select_kept_prunes_and_limits():
    p = pool()
    helm = next(g for s, g in p.candidates if g.item_id == 2001)
    ring = next(g for s, g in p.candidates if g.item_id == 3003)
    pass1 = {helm.key: {"f": 1.0}, ring.key: {"f": -5.0}}
    kept = select_kept(p, pass1, {"f": 1.0}, {"armor": 2, "finger": 3}, prune_below=-2.0)
    assert kept.get("head") == [helm]
    assert "finger" not in kept
