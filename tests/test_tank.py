import json
import sqlite3

from paf import healer, tank
from paf.corpus.db import SCHEMA
from paf.tank import debuff_cycles


def corpus():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    tank.ensure_table(con)
    for k in range(4):  # 60 s kills; a buster "Crush" at 30 s; taunts at 20 and 40 s
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 4, 60, 'done')", (rep,))
        con.execute("INSERT INTO ranked(report, fight_id, actor_id, rank_pos) VALUES(?, 1, 5, 1)", (rep,))
        melee = [100.0] * 12
        crush = [0.0] * 12
        crush[6] = 900.0
        con.execute("INSERT INTO tank_damage VALUES(?, 1, 5.0, ?)", (rep, json.dumps({"Melee": melee, "Crush": crush})))
        for t in (20.0, 40.0):
            con.execute("INSERT INTO player_cast(report, fight_id, actor_id, ability_id, type, t) "
                        "VALUES(?, 1, 5, 355, 'cast', ?)", (rep, t))
    return con


def test_tank_busters_hitters_and_swaps():
    con = corpus()
    curve, by, hitters = tank.tank_curves(con, 9, 4, 60.0)
    assert curve[0] == 100.0 and curve[6] == 1000.0
    assert [h[0] for h in hitters] == ["Melee", "Crush"]  # 1200 vs 900 of the tank's damage
    found = tank.tank_busters(curve, by)
    assert [(m.t, m.boss_spell) for m in found] == [(30.0, "Crush")]
    times, per_kill = tank.swaps(con, 9, 4)
    assert times == [20.0, 40.0] and per_kill == 2
    p = tank.TankPrep("Boss", "heroic", "Protection Warrior", 4, 60.0, curve, found, hitters,
                      [healer.Cooldown("Shield Wall", 871, 0.9, 1.0, [29.0], ["0:30 Crush"])], times, per_kill,
                      [("Shield Block", 0.6)], [], [], ["Taunt at 3 stacks."])
    page = tank.render(p)
    assert "What hits you, and when" in page and "Crush" in page and "Tank swaps" in page
    assert "Shield Wall" in page and "Shield Block" in page and "Taunt at 3 stacks." in page
    sheet = tank.render_sheet(p)  # the four-tab sheet the app shows: its lead names the tanks' own danger
    assert "What hits the top tanks the most: Melee" in sheet and "The top tanks' biggest moment: 0:30, Crush" in sheet



def test_the_debuffs_a_tank_swaps_on():
    """Vashnik heroic (2026-10-20): Dripping Fangs is one debuff on the tank (no stacks) that stays until the swap;
    a stacking debuff gives its peak; another player's debuffs are not the tank's."""
    ev = [{"type": "applydebuff", "abilityGameID": 1, "targetID": 7, "timestamp": 0},
          {"type": "applydebuffstack", "abilityGameID": 1, "targetID": 7, "stack": 3, "timestamp": 5000},
          {"type": "removedebuff", "abilityGameID": 1, "targetID": 7, "timestamp": 9000},
          {"type": "applydebuff", "abilityGameID": 2, "targetID": 7, "timestamp": 10000},
          {"type": "removedebuff", "abilityGameID": 2, "targetID": 7, "timestamp": 38000},
          {"type": "applydebuff", "abilityGameID": 1, "targetID": 9, "timestamp": 1000}]
    assert debuff_cycles(ev, 7) == [(1, 3, 9.0), (2, 1, 28.0)]


def test_the_debuff_the_tanks_swap_on():
    from paf.tank import swap_debuff

    nek = {"Hollowing Strikes": (8, 29.4), "Corpse Blight": (6, 28.8), "Possession Barrage": (1, 2.0)}
    assert swap_debuff(nek, {"Hollowing Strikes", "Possession Barrage"}) == "Hollowing Strikes"
    vash = {"Virulent Fumes": (1, 0.7), "Dripping Fangs": (1, 32.0)}
    assert swap_debuff(vash, {"Dripping Fangs"}) == "Dripping Fangs"
    assert swap_debuff(vash, set()) == ""


def test_the_journal_says_when_taunts_stop_working(monkeypatch):
    """Nek'zali heroic: Uncoiled Rage "grants immunity to Taunt effects"; the swaps section said nothing of it."""
    from types import SimpleNamespace

    from paf import bossguide, tank

    text = ("Upon reaching full energy, Nek'zali gains her full potential. "
            "Additionally, grants immunity to Taunt effects.")
    rage = SimpleNamespace(title="Uncoiled Rage", text="", spell_id=1, kind="ability", children=[], flags=[])
    monkeypatch.setattr(bossguide, "describe", lambda sid: text)
    monkeypatch.setattr("paf.mechanics.walk", lambda sections: [(0, s) for s in sections])
    assert tank.taunt_immunity([rage], "heroic") == [("Uncoiled Rage", text)]


def test_a_long_defensive_is_said_beside_a_short_one():
    # Protection Warrior, Nek'zali (round 79, the owner): 38% Spell Reflection for 0:35, Shield Wall's 23% unsaid
    con = corpus()
    curve, by, hitters = tank.tank_curves(con, 9, 4, 60.0)
    found = tank.tank_busters(curve, by)
    sw = healer.Cooldown("Shield Wall", 871, 0.9, 1.0, [29.0], ["0:30 Crush"], support=[0.23],
                         presses=[[29.0]] * 23 + [[50.0]] * 67, n_all=100, lasts=[60.0] * 100)
    sr = [[28.0]] * 38 + [[50.0]] * 52 + [[]] * 10
    p = tank.TankPrep("Boss", "heroic", "Protection Warrior", 4, 60.0, curve, found, hitters, [sw], [], 0,
                      [("Shield Block", 0.6)], [], [], [],
                      short_defs=[("Spell Reflection", 0.9, 1.0, [28.0], [], [0.38], sr, [60.0] * 100)])
    sheet = tank.render_sheet(p)
    assert "press Spell Reflection for it (about 0:28); 23% press Shield Wall, a long defensive (about 0:29)" in sheet
