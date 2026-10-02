import sqlite3

from paf.actions import actions
from paf.assigns import Mechanic
from paf.corpus.db import SCHEMA


def corpus():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.execute("INSERT INTO npc VALUES(1, 'Boss', 1)")
    con.execute("INSERT INTO npc VALUES(2, 'Rawling', 0)")
    con.execute("INSERT INTO npc VALUES(3, 'Clutch', 0)")
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 5, 400, 'done')", (rep,))
        for i in range(3):
            con.execute("INSERT INTO add_instance VALUES(?, 1, 50, ?, 2, 30, 50, 1)", (rep, i + 1))
        con.execute("INSERT INTO add_instance VALUES(?, 1, 60, 1, 3, 10, 400, 0)", (rep,))
        con.execute("INSERT INTO damage_by_target VALUES(?, 1, 1, 'Rawling', 300)", (rep,))
        con.execute("INSERT INTO damage_by_target VALUES(?, 1, 1, 'Boss', 700)", (rep,))
    return con


def test_actions_from_the_logs():
    mechs = [Mechanic("interrupt:1", "Anguished Cry", "interrupt", [60.0], 0.0, 5, 8, 12, 0.71),
             Mechanic("interrupt:2", "Malice", "interrupt", [90.0], 0.0, 1, 2, 2, 0.06),
             Mechanic("debuff:3", "Doomscale Shell", "debuff", [200.0], 3.0, 5, 1, 1, 0.0),
             Mechanic("debuff:4", "Doomscale Shell", "debuff", [210.0], 3.0, 5, 1, 1, 0.0)]
    out = actions(corpus(), 9, 5, "Elemental", mechs, {"Rawling": 0.54}, {"Boss"})
    text = [a.text for a in out]
    assert text[0] == ("Kill the Rawling (~3 per kill): the top raids kill them in ~20 s; top Elemental players "
                       "put 54% of their damage on them while they are up.")
    assert any(t.startswith("Interrupt Anguished Cry: top Elemental players kick it in 71%") for t in text)
    assert any(t.startswith("Malice is interrupted ~2 times per kill, mostly by other classes") for t in text)
    assert sum(t.startswith("Doomscale Shell: 1 player per kill") for t in text) == 1  # deduplicated, singular
    assert any(t.startswith("Clutch: the top raids do not kill it") for t in text)


def test_contact_debuffs_explain_units_nobody_kills():
    from paf.actions import contact_debuffs

    con = corpus()
    con.execute("INSERT INTO ability VALUES(77, 'Noxious Shell')")
    for k in range(10):
        con.execute("INSERT INTO mech_status VALUES(?, 1, 'x')", (f"r{k}",))
        for _ in range(4):
            con.execute("INSERT INTO mech_event VALUES(?, 1, 'debuff', 77, 5, 30)", (f"r{k}",))
    contact = contact_debuffs(con, 9, 5, {"Clutch": ["Noxious Shell", "Rancid Yolk"]})
    assert contact == {"Clutch": [("Noxious Shell", 4.0)]}
    out = actions(con, 9, 5, "Elemental", [], {}, {"Boss"}, contact)
    clutch = next(a for a in out if a.name == "Clutch")
    assert clutch.kind == "contact" and "Noxious Shell (~4 per kill)" in clutch.text
