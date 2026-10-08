import sqlite3
from types import SimpleNamespace

from paf import comp, raidreview, workshop_views
from paf.corpus.db import SCHEMA

SPECS = (("Subtlety", "Rogue"), ("Frost", "DeathKnight"), ("Fire", "Mage"), ("Balance", "Druid"),
         ("Arcane", "Mage"), ("Unholy", "DeathKnight"))


def corpus():
    """Ten top kills of 100 s with six damage dealers: two of them (a Subtlety Rogue and a Frost DK, rogue first)
    take the Echo (an assigned add); everyone hits the Slime a little (a whole-raid add). The ranked Fire Mage of
    each kill is a top player: left out."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 5, 100, 'done')", (rep,))
        con.execute("INSERT INTO ranked(report, fight_id, actor_id) VALUES(?, 1, 99)", (rep,))
        rows = [(i + 1, cls, spec, {"Boss": 1000, "Slime": 100, "Echo": {0: 300, 1: 250}.get(i, 0)})
                for i, (spec, cls) in enumerate(SPECS)]
        rows.append((99, "Mage", "Fire", {"Boss": 2000, "Slime": 900}))
        for actor, cls, spec, dmg in rows:
            con.execute("INSERT INTO player VALUES(?, 1, ?, ?, ?, 0, ?)", (rep, actor, cls, spec, sum(dmg.values())))
            for target, amount in dmg.items():
                if amount:
                    con.execute("INSERT INTO damage_by_target VALUES(?, 1, ?, ?, ?)", (rep, actor, target, amount))
    return con


def pull():
    players = [("Rogue", "Subtlety Rogue", 14.0), ("Dk", "Frost DeathKnight", 13.0), ("Fire", "Fire Mage", 12.0),
               ("Moon", "Balance Druid", 11.0), ("Heal", "Restoration Druid", 1.0)]
    targets = {"Rogue": {"Boss": 1100, "Slime": 100, "Echo": 200}, "Dk": {"Boss": 1200, "Slime": 100},
               "Fire": {"Boss": 1100, "Slime": 100}, "Moon": {"Boss": 1100}, "Heal": {"Boss": 10}}
    return SimpleNamespace(fight="this boss, kill of 1:40", duration=100.0, players=players, targets=targets)


def rows():
    con = corpus()
    targets, _ = raidreview.references(con, 9, 5, "Boss")
    return comp.assign(pull(), comp.references(con, 9, 5, targets))


def test_the_specs_that_hit_an_assigned_add_the_most_are_put_on_it():
    echo = next(a for a in rows() if a.target == "Echo")
    assert not echo.whole_raid and echo.players == 2
    assert [s for s, _, _ in echo.ranking[:2]] == ["Subtlety Rogue", "Frost DeathKnight"]
    assert [n for n, _ in echo.proposed] == ["Rogue", "Dk"]


def test_a_whole_raid_add_lists_who_missed_it_and_the_ranked_player_is_left_out():
    slime = next(a for a in rows() if a.target == "Slime")
    assert slime.whole_raid and slime.players == 0 and not slime.proposed
    assert [n for n, *_ in slime.missed] == ["Moon"]
    fire = next(r for r in slime.ranking if r[0] == "Fire Mage")
    assert round(fire[1]) == 1  # 100 damage in 100 s, the ranked player's 900 left out


def test_the_page():
    page = workshop_views.render({"kind": "comp", **comp.to_dict("Boss", "this boss, kill of 1:40", rows())})
    assert "Who hits what in your raid" in page and "Put them on it" in page and "Hardly hit it" in page


def test_a_spec_change_for_boss_damage():
    dps = comp.boss_dps(corpus(), 9, 5, {"Boss"})
    assert round(dps["Fire Mage"]) == 10  # 1000 in 100 s: the ranked Fire Mage's 2000 left out
    out = comp.swaps(pull(), {"Fire Mage": 10.0, "Arcane Mage": 12.0}, {"Mage": ["Arcane Mage", "Fire Mage"]})
    assert [(x.name, x.better, round(x.gain, 2)) for x in out] == [("Fire", "Arcane Mage", 0.2)]
    page = workshop_views.render({"kind": "comp", **comp.to_dict("Boss", "", rows(), out)})
    assert "Change spec for more boss damage" in page


def test_the_best_pull_without_the_deaths():
    from paf import wipe

    p = wipe.Pull(1, 60.0, 0.5, 300.0, [50.0, 50.0, 50.0, 50.0], lost=[0.0, 0.0, 50.0, 50.0])
    assert round(p.kill_time()) == 90 and round(p.kill_time("no_deaths")) == 60
    page = workshop_views.render({"kind": "wipe", **wipe.to_dict(p, "Boss", 70.0, 50.0)})
    assert "Without the deaths" in page and "<svg" in page


def test_the_night_tracker():
    from paf import tracker

    assert tracker.kind("Healthstone") == "healthstone" and tracker.kind("Pierre de soins") == "healthstone"
    assert tracker.kind("Silvermoon Health Potion") == "health" and tracker.kind("Potion de soins") == "health"
    assert tracker.kind("Potion of Recklessness") == "damage" and tracker.kind("Lightfused Mana Potion") is None
    assert tracker.kind("Create Healthstone") is None
    p = tracker.PlayerPull(deaths=[100.0], healthstone=[120.0])
    assert p.died_bare  # the healthstone came after the death
    row = tracker.PullRow(1, "Boss", 5, False, 300.0, 0.2, {"Moon": p, "Dk": tracker.PlayerPull(damage=[1.0])})
    d = tracker.to_dict("x", [row], {"Moon": "Druid-Balance"})
    assert d["summary"]["Moon"]["bare"] == 1 and d["summary"]["Dk"]["pulls_damage_potion"] == 1
    page = workshop_views.render({"kind": "night", **d})
    assert "1 pulls, 1 deaths before the wipes" in page and "Pull by pull" in page


def test_the_raid_tab_of_the_sheet_shows_the_raid_tools():
    from paf.prep_report import PrepData, render

    d = PrepData("Boss", "mythic", "Elemental", "X", duration=300)
    d.raid_tools = {"comp": comp.to_dict("Boss", "this boss, kill of 1:40", rows())}
    html = render(d)
    assert "Who hits what in your raid" in html and "Put them on it" in html
    assert "Your best pull, in detail" not in html  # no wipe in that log: nothing shown
