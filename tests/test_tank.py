import json
import sqlite3

from paf import healer, tank
from paf.corpus.db import SCHEMA
from paf.tank import stack_peaks


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



def test_the_stacks_a_tank_swaps_at():
    """Vashnik heroic: Dripping Fangs stacks on the tank, then falls off when the other tank takes the boss; each
    cycle's peak is the count the top tanks swap at (a one-stack debuff is no stacking debuff)."""
    ev = [{"type": "applydebuff", "abilityGameID": 1, "targetID": 7},
          {"type": "applydebuffstack", "abilityGameID": 1, "targetID": 7, "stack": 2},
          {"type": "applydebuffstack", "abilityGameID": 1, "targetID": 7, "stack": 3},
          {"type": "removedebuff", "abilityGameID": 1, "targetID": 7},
          {"type": "applydebuff", "abilityGameID": 2, "targetID": 7},
          {"type": "removedebuff", "abilityGameID": 2, "targetID": 7},
          {"type": "applydebuffstack", "abilityGameID": 1, "targetID": 9, "stack": 5}]
    assert stack_peaks(ev, 7) == [(1, 3)]
