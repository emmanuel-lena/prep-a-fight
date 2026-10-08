import sqlite3
from types import SimpleNamespace

from paf import raidreview, workshop_views
from paf.corpus.db import SCHEMA


def corpus():
    """Ten top kills: the boss and an 'Echo'; the top Unholy DKs never hit the Echo, the Balance Druids do."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 5, 300, 'done')", (rep,))
        for actor, cls, spec, boss, echo in ((1, "DeathKnight", "Unholy", 100, 0), (2, "Druid", "Balance", 70, 30)):
            con.execute("INSERT INTO player VALUES(?, 1, ?, ?, ?, 0, ?)", (rep, actor, cls, spec, boss + echo))
            con.execute("INSERT INTO damage_by_target VALUES(?, 1, ?, 'Boss', ?)", (rep, actor, boss))
            if echo:
                con.execute("INSERT INTO damage_by_target VALUES(?, 1, ?, 'Echo', ?)", (rep, actor, echo))
    return con


def raid(dk_echo: float, druid_echo: float):
    return SimpleNamespace(fight="this boss, kill of 5:00", duration=300.0, players=[
        ("Dk", "Unholy DeathKnight", 1.0), ("Moon", "Balance Druid", 1.0), ("Heal", "Restoration Druid", 1.0)],
        targets={"Dk": {"Boss": 100 - dk_echo, "Echo": dk_echo}, "Moon": {"Boss": 100 - druid_echo, "Echo": druid_echo},
                 "Heal": {}})


def test_a_player_padding_a_covered_target_goes_back_to_the_boss():
    targets, habits = raidreview.references(corpus(), 9, 5, "Boss")
    assert [t.name for t in targets] == ["Boss", "Echo"] and habits["Unholy DeathKnight"]["Echo"] == 0.0
    r = raidreview.review(raid(dk_echo=12, druid_echo=30), targets, habits, "Boss")
    dk = next(p for p in r.players if p.name == "Dk")
    assert dk.verdict == "to_boss" and dk.target == "Echo" and round(dk.moved, 2) == 0.12
    assert all(p.name != "Heal" for p in r.players)  # healers are not judged


def test_a_short_target_gets_the_spec_that_takes_it():
    targets, habits = raidreview.references(corpus(), 9, 5, "Boss")
    r = raidreview.review(raid(dk_echo=0, druid_echo=2), targets, habits, "Boss")
    echo = next(t for t in r.targets if t.name == "Echo")
    assert not echo.covered
    moon = next(p for p in r.players if p.name == "Moon")
    assert moon.verdict == "to_target" and moon.target == "Echo"
    page = workshop_views.render({"kind": "review", **raidreview.to_dict(r)})
    assert "1 player can do better for the boss" in page and "Your raid lacks damage there." in page
