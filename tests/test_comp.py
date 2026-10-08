import sqlite3
from types import SimpleNamespace

from paf import comp, raidreview, workshop_views
from paf.corpus.db import SCHEMA


def corpus():
    """Ten top kills of 300 s: Fire Mages do 400 on the boss and never touch the Echo; Frost Mages do 300 and take
    the Echo in half the kills (100 there); Balance Druids always put 30 of 100 on it."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 5, 1, 'done')", (rep,))
        rows = ((1, "Mage", "Fire", 400, 0), (2, "Mage", "Frost", 300 - 100 * (k % 2), 100 * (k % 2)),
                (3, "Druid", "Balance", 70, 30))
        for actor, cls, spec, boss, echo in rows:
            con.execute("INSERT INTO player VALUES(?, 1, ?, ?, ?, 0, ?)", (rep, actor, cls, spec, boss + echo))
            con.execute("INSERT INTO damage_by_target VALUES(?, 1, ?, 'Boss', ?)", (rep, actor, boss))
            if echo:
                con.execute("INSERT INTO damage_by_target VALUES(?, 1, ?, 'Echo', ?)", (rep, actor, echo))
    return con


def pull(mage_spec: str = "Frost Mage"):
    return SimpleNamespace(fight="this boss, kill of 5:00", duration=1.0, players=[
        ("Mago", mage_spec, 300.0), ("Moon", "Balance Druid", 100.0), ("Heal", "Restoration Druid", 10.0)],
        targets={"Mago": {"Boss": 300.0}, "Moon": {"Boss": 70.0, "Echo": 30.0}, "Heal": {"Boss": 10.0}})


def propose(rc, specs=None):
    con = corpus()
    targets, _ = raidreview.references(con, 9, 5, "Boss")
    stats = comp.spec_stats(con, 9, 5, [t.name for t in targets])
    return comp.propose(rc, targets, stats, {"Mage": ["Fire Mage", "Frost Mage"]} if specs is None else specs)


def test_the_stronger_spec_of_the_class_goes_on_the_boss():
    c = propose(pull())
    mago = next(p for p in c.picks if p.name == "Mago")
    # Frost at the median (300 of 300): as Fire, 400 on the boss
    assert mago.spec == "Fire Mage" and mago.job == "Boss" and round(mago.boss) == 400
    assert c.gain > 0.2 and not c.notes
    heal = next(p for p in c.picks if p.name == "Heal")
    assert heal.role == "support" and heal.spec == "Restoration Druid"


def test_no_spec_change_without_the_class_specs():
    c = propose(pull(), specs={})
    assert next(p for p in c.picks if p.name == "Mago").spec == "Frost Mage"


def test_a_target_short_of_damage_gets_the_cheapest_player():
    # the Echo needs the top raids' weakest quarter of its share: the Druid covers it at their focus
    c = propose(pull())
    assert c.got["Echo"] >= c.need["Echo"] - 1
    moon = next(p for p in c.picks if p.name == "Moon")
    assert moon.job in ("Boss", "Echo")
    page = workshop_views.render({"kind": "comp", **comp.to_dict(c)})
    assert "Your raid's best comp" in page and "Spec changes" in page and "Who goes where" in page
