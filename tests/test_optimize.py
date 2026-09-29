from collections import OrderedDict

from paf.fight import AddWave, Fight, Window
from paf.optimize import (
    Rule,
    apply_rules,
    cd_key,
    fight_context,
    fight_rules,
    secondary_fight,
    tops_alignment,
)


def fight():
    return Fight("B", 300, add_waves=[AddWave(60, 5, 20), AddWave(150, 1, 20, "Heart", scalable=False)],
                 movement=[Window(100, 5)], lust_time=0, power_infusion=[30])


def test_cd_key():
    assert cd_key("ascendance,if=x") == "ascendance"
    assert cd_key("use_item,slot=trinket1,if=x") == "use_item:trinket1"
    assert cd_key("use_item,name=font_of_venomous_rage") == "use_item:font_of_venomous_rage"
    assert cd_key("lightning_bolt") is None


def test_rules_and_apply():
    rules = {r.name: r for r in fight_rules(fight(), long_cd=True)}
    assert {"default", "on_cooldown", "hold_adds_20", "hold_adds_60", "add_waves", "secondary_targets",
            "lust_pi", "not_before_move"} <= set(rules)
    assert rules["hold_adds_30"].condition("a") == "(a)&(raid_event.adds.up|raid_event.adds.in>30|fight_remains<30)"
    assert rules["on_cooldown"].condition("a") is None
    apl = OrderedDict([("", ["ascendance,if=a", "lightning_bolt"])])
    lines = apply_rules(apl, {"ascendance": Rule("x", "", lambda old: "b")})
    assert lines == ["actions=ascendance,if=b", "actions+=/lightning_bolt"]


def test_secondary_fight_keeps_only_unique_targets():
    f = secondary_fight(fight())
    assert [w.name for w in f.add_waves] == ["Heart"]
    assert secondary_fight(Fight("B", 100, add_waves=[AddWave(1, 3, 10)])) is None


def test_vulnerable_windows():
    from paf.fight import Vulnerable

    f = fight()
    f.vulnerable = [Vulnerable(200, 20, 2.5, "Heart")]
    assert any("vulnerable,first=200,duration=20,cooldown=9999,multiplier=2.5" in e for e in f.to_simc())
    rules = {r.name for r in fight_rules(f, long_cd=True)}
    assert {"vulnerable_windows", "hold_vulnerable_60"} <= rules
    assert "Heart x2.5" in fight_context(f, 205)


def test_fight_variants_and_flags():
    from paf.fight import Vulnerable
    from paf.optimize import Alignment, Plan, fight_variants, sanity_flags

    f = fight()
    f.vulnerable = [Vulnerable(200, 20, 3.0, "Heart")]
    v = fight_variants(f)
    assert v["amp halved"].vulnerable[0].multiplier == 2.0
    assert v["adds die 25% faster"].add_waves[0].lifetime == 15.0
    assert v["adds die 25% faster"].add_waves[1].lifetime == 20  # unique units untouched
    rules = {r.name: r for r in fight_rules(f, long_cd=True)}
    plan = Plan("total", {"ascendance": rules["hold_adds_20"]}, gain=8.0, error=0.1,
                sensitivity={"amp halved": 7.0, "adds die 25% faster": 0.05})
    align = [Alignment("Ascendance", 50, 0.2, 0.6, 0.2, 0.1)]
    flags = sanity_flags(plan, align)
    assert any("large gain" in x for x in flags)
    assert any("not robust" in x and "adds die" in x for x in flags)
    assert any("top players keep it for the secondary target" in x for x in flags)
    assert not plan.robust


def test_large_gain_not_flagged_when_validated_robust_and_agreeing():
    from paf.optimize import Plan, sanity_flags

    rules = {r.name: r for r in fight_rules(fight(), long_cd=True)}
    plan = Plan("boss", {"ascendance": rules["secondary_targets"]}, gain=10.0, error=0.1,
                sensitivity={"adds die 25% faster": 9.0})
    assert sanity_flags(plan, [], validation=0.97) == []
    assert any("not validated" in f for f in sanity_flags(plan, [], validation=None))
    assert any("not validated" in f for f in sanity_flags(plan, [], validation=0.74))


def test_fight_context():
    assert fight_context(fight(), 65) == "adds"
    assert fight_context(fight(), 35) == "lust, PI"
    assert fight_context(fight(), 97) == "move soon"


def test_tops_alignment():
    class Ab:
        id, name, utility = 1, "Ascendance", False

    class TL:
        abilities = [Ab()]
        players = [{"casts": {1: [152.0, 155.0, 290.0]}} for _ in range(4)]

    a = tops_alignment(TL(), fight())[0]
    assert round(a.in_units, 2) == 0.67 and a.in_adds == 0.0
    assert 0 < a.units_cover < a.in_units
