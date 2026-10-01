import sqlite3

from paf.corpus.db import SCHEMA
from paf.raidneed import AOE, SINGLE, UNKNOWN, AddType, archetype, archetypes, report_code, verdicts


def add(focus=None):
    return AddType("Amani", 100, 18.0, 0.15, focus or {"Balance Druid": 0.44, "Elemental Shaman": 0.33,
                                                        "Arms Warrior": 0.10}, 0.25, tops_rate=1000.0, tops_low=900.0)


def test_report_code():
    assert report_code("https://www.warcraftlogs.com/reports/ZJRNbP1DCqQ3grcV#fight=4") == "ZJRNbP1DCqQ3grcV"
    assert report_code("ZJRNbP1DCqQ3grcV") == "ZJRNbP1DCqQ3grcV"


def test_verdicts_boss_pad_and_lacking_cleave():
    t = add()
    you = ("Elemental Shaman", 1000.0)  # 330 on the adds when padding
    strong = [("Balance Druid", 2500.0)]  # 1100: above the top raids' median without you
    assert verdicts([t], strong, you)[0].verdict == "boss"
    middle = [("Balance Druid", 1500.0)]  # 660 without you, 990 with you: you make the difference
    v = verdicts([t], middle, you)[0]
    assert v.verdict == "pad" and "make the difference" in v.reason and round(v.without_you, 2) == 0.66
    weak = [("Arms Warrior", 3000.0)]  # 300 / 630: below even with you
    assert "lacks cleave" in verdicts([t], weak, you)[0].reason


def test_archetypes_by_focus_on_this_boss():
    t = add()
    assert archetype(t, "Balance Druid") == AOE and archetype(t, "Arms Warrior") == SINGLE
    groups = archetypes([t], [("A", "Balance Druid", 1.0), ("B", "Arms Warrior", 1.0), ("C", "Holy Priest", 1.0),
                              ("D", "Affliction Warlock", 1.0)])
    assert groups[AOE] == ["A (Balance Druid)"] and groups[SINGLE] == ["B (Arms Warrior)"]  # healers left out
    assert groups[UNKNOWN] == ["D (Affliction Warlock)"]  # too few in the logs: said, not guessed


def test_add_types_from_a_tiny_corpus():
    from paf.raidneed import add_types

    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.execute("INSERT INTO npc VALUES(1, 'Boss', 1)")
    con.execute("INSERT INTO npc VALUES(2, 'Amani', 0)")
    for k in range(16):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 4, 100, 'done')", (rep,))
        con.execute("INSERT INTO add_instance VALUES(?, 1, 50, 1, 2, 10, 30, 1)", (rep,))
        for actor, spec, cls, total, on_add in ((1, "Balance", "Druid", 100000, 1000 * 20 * 0.5),
                                                (2, "Arms", "Warrior", 100000, 1000 * 20 * 0.1)):
            con.execute("INSERT INTO player VALUES(?, 1, ?, ?, ?, 300, ?)", (rep, actor, cls, spec, total))
            con.execute("INSERT INTO damage_by_target VALUES(?, 1, ?, 'Amani', ?)", (rep, actor, on_add))
            con.execute("INSERT INTO damage_by_target VALUES(?, 1, ?, 'Boss', ?)", (rep, actor, total - on_add))
    types = add_types(con, 9, 4)
    assert [t.name for t in types] == ["Amani"]
    t = types[0]
    assert round(t.focus["Balance Druid"], 2) == 0.5 and round(t.focus["Arms Warrior"], 2) == 0.1
    assert round(t.lifetime) == 20 and round(t.tops_rate) == 600  # 1000 DPS x 0.5 + 1000 x 0.1
