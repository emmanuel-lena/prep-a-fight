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


def test_two_pulls_side_by_side():
    from paf import pulldiff, wipe

    wipes = [{"id": i, "kill": False, "bossPercentage": pct, "startTime": 0, "endTime": 300_000}
             for i, pct in ((1, 60.0), (2, 20.0), (3, 40.0))]
    assert [f["id"] for f in pulldiff.default_pair(wipes)] == [3, 2]  # the two best wipes
    kill = {"id": 4, "kill": True, "bossPercentage": 0.01, "startTime": 0, "endTime": 300_000}
    assert [f["id"] for f in pulldiff.default_pair(wipes + [kill])] == [2, 4]  # the best wipe, then the kill

    def side(fid, left, dead, boss_dps):
        p = wipe.Pull(fid, 60.0, left, 400.0, [100.0] * 4, lost=[0.0] * 4, targets={"Boss": 300.0, "Add": 100.0},
                      bosses={"Boss"})
        pl = pulldiff.Player("Me", "Rogue-Subtlety", 100.0, boss_dps, 0.9, {"Backstab": 50.0}, {"Shadow Blades": 1},
                             {"Shadow Blades": [5.0]}, {"Symbols of Death": 0.5})
        return pulldiff.Side(fid, False, left, 60.0, p, {"Boss": 0.75, "Add": 0.25}, {"X": [10.0]} if dead else {},
                             int(dead), pl)
    d = pulldiff.to_dict("Boss", side(1, 0.6, True, 50.0), side(2, 0.2, False, 80.0))
    kinds = [h["kind"] for h in d["highlights"]]
    assert "good" in kinds and any("on the boss in B" in h["text"] for h in d["highlights"])
    page = workshop_views.render({"kind": "diff", **d})
    assert "What changed, biggest first" in page and "Casts per minute" in page and "<svg" in page



def test_bonus_rolls_rank_the_bosses():
    d = {"kind": "bonusroll", "ilvl": 300, "error": 0.2,
         "ev": [{"boss": "A", "ev": 0.4, "n": 5}, {"boss": "B", "ev": 1.2, "n": 4}],
         "rows": [{"boss": "B", "name": "Ring", "gain": 3.0, "slot": "finger", "item_id": 1},
                  {"boss": "A", "name": "Belt", "gain": 0.1, "slot": "waist", "item_id": 2}]}
    page = workshop_views.render(d)
    assert "Bonus roll on B first" in page and page.index(">B<") < page.index(">A<")
    assert "Ring" in page and "no real upgrade" in page

    d["ev"] = [{"boss": "A", "ev": 0.1, "n": 5}]
    assert "No boss stands out for a bonus roll" in workshop_views.render(d)  # under the noise
