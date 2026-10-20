import json

from paf.corpus import db
from paf.corpus.collect import parse_kill, write_kill

START = 1_000_000


def payload():
    return {
        "fights": [{
            "id": 7, "name": "Boss", "encounterID": 99, "kill": True, "difficulty": 4, "size": 20,
            "startTime": START, "endTime": START + 300_000, "averageItemLevel": 310.0,
            "phaseTransitions": [{"id": 1, "startTime": START}, {"id": 2, "startTime": START + 120_000}],
            "enemyNPCs": [{"id": 50, "gameID": 1000, "instanceCount": 1, "petOwner": None},
                          {"id": 51, "gameID": 2000, "instanceCount": 2, "petOwner": None}],
        }],
        "phases": [{"encounterID": 99, "phases": [{"id": 1, "name": "P1", "isIntermission": False},
                                                   {"id": 2, "name": "P2", "isIntermission": False}]}],
        "masterData": {
            "actors": [{"id": 50, "name": "Boss", "gameID": 1000, "type": "NPC", "subType": "Boss"},
                       {"id": 51, "name": "Add", "gameID": 2000, "type": "NPC", "subType": "NPC"},
                       {"id": 3, "name": "Someone", "gameID": 1, "type": "Player", "subType": "Shaman"}],
            "abilities": [{"gameID": 114050, "name": "Ascendance"}],
        },
        "dmg": {"data": {"entries": [
            {"id": 3, "name": "Someone", "type": "Shaman", "icon": "Shaman-Elemental", "total": 60_000_000,
             "itemLevel": 312, "targets": [{"name": "Boss", "total": 40_000_000},
                                           {"name": "Add", "total": 20_000_000}]},
            {"id": 4, "name": "Other", "type": "Mage", "icon": "Mage-Fire", "total": 50_000_000,
             "targets": [{"name": "Boss", "total": 50_000_000}]},
        ]}},
        "deaths": {"data": [{"timestamp": START + 80_000, "type": "death", "targetID": 51, "targetInstance": 1}]},
        "debuffs": {"data": [
            {"timestamp": START + 60_000, "type": "applydebuff", "targetID": 51, "targetInstance": 1},
            {"timestamp": START + 61_000, "type": "applydebuff", "targetID": 51, "targetInstance": 2},
            {"timestamp": START + 1_000, "type": "applydebuff", "targetID": 50},
        ]},
        "ecasts": {"data": [{"timestamp": START + 10_000, "type": "cast", "sourceID": 50, "abilityGameID": 5}]},
    }


def test_parse_kill():
    p = parse_kill(payload(), 7, "Someone")
    assert p["fight"]["duration_s"] == 300
    assert p["ranked_actor"] == 3
    assert p["phases"] == [(1, "P1", 0, 0.0), (2, "P2", 0, 120.0)]
    # boss excluded from adds; the add without a death lives until the end of the fight
    assert p["adds"] == [(51, 1, 2000, 60.0, 80.0, 1), (51, 2, 2000, 61.0, 300.0, 0)]
    assert (4, "Mage", "Fire", None, 50_000_000) in p["players"]
    assert (3, "Add", 20_000_000) in p["damage"]


def test_parse_kill_anonymized_uses_spec_and_dps():
    p = parse_kill(payload(), 7, "Anonymous", ("Shaman", "Elemental", 200_000))
    assert p["ranked_actor"] == 3


def test_write_kill(tmp_path):
    con = db.connect(tmp_path / "c.sqlite")
    con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty) VALUES('R', 7, 99, 4)")
    con.execute("INSERT INTO ranked(report, fight_id, name, talents_json) VALUES('R', 7, 'Someone', ?)",
                (json.dumps([]),))
    p = parse_kill(payload(), 7, "Someone")
    pcasts = [{"timestamp": START + 5_000, "type": "cast", "abilityGameID": 114050, "x": 1234, "y": -500,
               "facing": 157, "resourceActor": 1}]
    write_kill(con, "R", 7, p, pcasts, [])
    row = con.execute("SELECT status, duration_s FROM fight").fetchone()
    assert tuple(row) == ("done", 300)
    assert con.execute("SELECT actor_id, name FROM ranked").fetchone()[:] == (3, None)
    assert con.execute("SELECT t, x, y FROM player_cast").fetchone()[:] == (5.0, 12.34, -5.0)
    write_kill(con, "R", 7, p, pcasts, [])  # re-fetch replaces rows instead of duplicating them
    assert con.execute("SELECT COUNT(*) FROM player_cast").fetchone()[0] == 1


def test_a_phase_that_comes_back_is_stored_once(tmp_path):
    """The Lost Explorers: Warcraft Logs gives phase 1, 2, then 1 and 2 again (issue #8)."""
    data = payload()
    data["fights"][0]["phaseTransitions"] = [{"id": 1, "startTime": START}, {"id": 2, "startTime": START + 60_000},
                                             {"id": 1, "startTime": START + 120_000},
                                             {"id": 2, "startTime": START + 180_000}]
    p = parse_kill(data, 7, "Someone")
    assert p["phases"] == [(1, "P1", 0, 0.0), (2, "P2", 0, 60.0)]
    con = db.connect(tmp_path / "c.sqlite")
    con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty) VALUES('R', 7, 99, 4)")
    write_kill(con, "R", 7, p, [], [])
    assert con.execute("SELECT COUNT(*) FROM phase").fetchone()[0] == 2


def test_a_boss_unit_is_up_from_the_ranked_players_first_hit():
    """Nek'zali's Echo of Jawae: the top players hit it from 1:32 while the cast that spawns it ends at 1:42."""
    import sqlite3

    from paf.corpus.analyze import kills_filter
    from paf.corpus.template import first_hit

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        "CREATE TABLE fight(report, fight_id, encounter_id, difficulty, status, cohort);"
        "CREATE TABLE ranked(report, fight_id, actor_id, spec);"
        "CREATE TABLE player_cast(report, fight_id, actor_id, ability_id, type, t, target_id);"
        "CREATE TABLE add_instance(report, fight_id, actor_id, game_id);"
        "CREATE TABLE npc(game_id, name, is_boss);"
        "INSERT INTO npc VALUES (7, 'Echo', 1);")
    for k, t in enumerate([90, 91, 92, 93, 95]):
        con.execute("INSERT INTO fight VALUES (?, 1, 3470, 4, 'done', NULL)", (f"r{k}",))
        con.execute("INSERT INTO ranked VALUES (?, 1, 5, 'Subtlety')", (f"r{k}",))
        con.execute("INSERT INTO add_instance VALUES (?, 1, 40, 7)", (f"r{k}",))
        for x in (t, t + 3):
            con.execute("INSERT INTO player_cast VALUES (?, 1, 5, 1, 'cast', ?, 40)", (f"r{k}", x))
    where, params = kills_filter(3470, 4)
    assert first_hit(con, where, params, "Subtlety", "Echo") == 92
    assert first_hit(con, where, params, "Subtlety", "Nobody") is None


def test_aura_amps_trust_the_game_data_over_the_measured_ratio():
    from paf.corpus.template import aura_amps
    from paf.fight import Window

    found = [("Dig In", 1.2, [(111.1, 25.0), (249.2, 25.0)], 12, 1286033),  # +30% in the game data, x1.2 measured
             ("Frenzy", 1.5, [(60.0, 10.0)], 12, 2),  # not in the game data: a candidate for the boss notes
             ("Shell", 0.9, [(30.0, 4.0)], 12, 3)]
    vulnerable, candidates, _ = aura_amps(found, {1286033: 1.3}.get)
    assert [(v.start, v.multiplier) for v in vulnerable] == [(111.1, 1.3), (249.2, 1.3)]
    assert [(v.name, v.multiplier) for v in candidates] == [("Frenzy (boss aura)", 1.5)]
    # the game data knows Uncoiled Wrath (damage done, not taken): not a candidate
    found.append(("Uncoiled Wrath", 1.34, [(393.4, 8.2)], 12, 1308583))
    _, candidates, _ = aura_amps(found, {1286033: 1.3}.get, lambda aid: aid == 1308583)
    # the Sentinels' Vitriolic Stasis: -99% in the game data, every 100 s -> immune windows, not an amp
    stasis = [("Vitriolic Stasis", 0.27, [(46.0, 10.0), (148.0, 12.0), (250.0, 8.0)], 12, 1284606)]
    assert aura_amps(stasis, {1284606: 0.01}.get) == ([], [], [Window(46.0, 10.0), Window(148.0, 12.0),
                                                                Window(250.0, 8.0)])
    assert [v.name for v in candidates] == ["Frenzy (boss aura)"]


def test_adds_that_never_die_come_from_the_damage_graph():
    """Nymrissa's Bubblefin Shorerunners flee into her bubble: no deaths, yet 60% of the top Elementals' damage."""
    import sqlite3

    from paf.corpus.db import SCHEMA
    from paf.corpus.units import npc_graph_windows, undying_waves

    series = [{"name": "Nymrissa Wavecaller", "type": "Boss", "data": [100.0] * 100},
              {"name": "Bubblefin Shorerunner", "type": "NPC",
               "data": [0.0] * 10 + [80.0] * 15 + [0.0] * 30 + [70.0] * 15 + [0.0] * 30},
              {"name": "Totem", "type": "NPC", "data": [1.0] * 100}]  # 1% of the damage: a mechanic
    assert npc_graph_windows(series, 200.0) == [("Bubblefin Shorerunner", 20.0, 30.0),
                                                 ("Bubblefin Shorerunner", 110.0, 30.0)]

    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO npc VALUES (?,?,?)", [(1, "Bubblefin Shorerunner", 0), (2, "Imp", 0), (3, "Egg", 0)])
    for k in range(5):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status) VALUES (?,1,3379,4,'done')",
                    (rep,))
        con.execute("INSERT INTO npc_status VALUES (?, 1)", (rep,))
        for start in (20 + k, 110 + k):
            con.execute("INSERT INTO npc_window VALUES (?, 1, 'Bubblefin Shorerunner', ?, 30)", (rep, start))
            con.executemany("INSERT INTO add_instance VALUES (?, 1, ?, 1, 1, ?, 300, 0)",
                            [(rep, 1000 + start * 20 + i, start + i) for i in range(15)])
        con.execute("INSERT INTO add_instance VALUES (?, 1, 99, 1, 2, 50, 60, 1)", (rep,))  # an add that dies
        con.execute("INSERT INTO add_instance VALUES (?, 1, 98, 1, 3, 70, 300, 0)", (rep,))
        con.execute("INSERT INTO npc_window VALUES (?, 1, 'Imp', 50, 10)", (rep,))  # tracked by its deaths instead
        con.executemany("INSERT INTO damage_by_target VALUES (?, 1, 5, ?, ?)",
                        [(rep, "Nymrissa Wavecaller", 78), (rep, "Bubblefin Shorerunner", 21), (rep, "Egg", 1)])
        con.execute("INSERT INTO npc_window VALUES (?, 1, 'Egg', 70, 20)", (rep,))  # 1% over the corpus: a mechanic
    assert undying_waves(con, 3379, 4) == [(22, 15, 30, "Bubblefin Shorerunner"),
                                           (112, 15, 30, "Bubblefin Shorerunner")]
    # the top players hit 5 of them at once (each lives ~10 s of a 30 s window): the sim gets 5, not 15
    con.executemany("INSERT INTO npc_stack VALUES (?, 1, 'Bubblefin Shorerunner', 5)", [(f"r{k}",) for k in range(4)])
    assert [n for _t, n, _l, _nm in undying_waves(con, 3379, 4)] == [5, 5]

    from paf.corpus.units import stacked_instances

    hits = [{"type": "damage", "targetID": 40, "targetInstance": i, "timestamp": 1000 + 500 * j}
            for j in range(4) for i in range(1, 6)]
    hits.append({"type": "damage", "targetID": 41, "targetInstance": 1, "timestamp": 1000})  # another unit type
    assert stacked_instances(hits, {40}, 0) == 5


def test_your_raid_sees_the_adds_that_never_die():
    """Nymrissa: 'no add type takes a real share of the damage', with 21% of it on Bubblefin Shorerunners."""
    import sqlite3

    from paf.corpus.db import SCHEMA
    from paf.raidneed import add_types

    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO npc VALUES (?,?,?)", [(1, "Bubblefin Shorerunner", 0), (2, "Nymrissa", 1)])
    for k in range(12):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status, duration_s) "
                    "VALUES (?,1,3379,4,'done',270)", (rep,))
        con.execute("INSERT INTO npc_status VALUES (?, 1)", (rep,))
        con.executemany("INSERT INTO npc_window VALUES (?, 1, 'Bubblefin Shorerunner', ?, 30)",
                        [(rep, 24), (rep, 69), (rep, 134)])
        con.executemany("INSERT INTO add_instance VALUES (?, 1, ?, 1, 1, ?, 270, 0)",
                        [(rep, 100 + i, 24 + i) for i in range(15)])
        for actor, spec, dmg_boss, dmg_add in ((1, "Elemental", 40, 60), (2, "Subtlety", 92, 8), (3, "Arcane", 85, 15)):
            con.execute("INSERT INTO player VALUES (?, 1, ?, 'X', ?, 300, ?)", (rep, actor, spec, dmg_boss + dmg_add))
            con.executemany("INSERT INTO damage_by_target VALUES (?, 1, ?, ?, ?)",
                            [(rep, actor, "Nymrissa", dmg_boss), (rep, actor, "Bubblefin Shorerunner", dmg_add)])
    types = add_types(con, 3379, 4)
    assert [t.name for t in types] == ["Bubblefin Shorerunner"]


def test_a_returning_unit_keeps_its_own_windows():
    """Ula'tek heroic (2026-10-20): the Venomous Heart is up at 2:04, 4:32 and 9:21, its first hit at 2:16; the
    first hit used to open the later windows at 2:16 too (the heart up from 2:16 to the end, every sim off). Only
    a hit just before a window opens it (Nek'zali's Echo: hit at 1:32, the cast ends at 1:42)."""
    from paf.corpus.template import opened_by_hit

    assert opened_by_hit(102.0, 160.0, 92.0) == (92.0, 160.0)
    assert opened_by_hit(272.0, 316.0, 136.5) == (272.0, 316.0)
    assert opened_by_hit(124.0, 168.0, 136.5) == (124.0, 168.0)


def test_a_spell_cast_on_another_player_is_one_cast():
    """A Holy Priest's Power Infusion (2026-10-20 corpus): logged on its target at 4.027 s and on the priest at
    4.049 s; the sheet said 6.0 a kill for 3 casts."""
    from paf.corpus.collect import without_twins

    casts = [{"type": "cast", "abilityGameID": 10060, "timestamp": 4027, "targetID": 11},
             {"type": "cast", "abilityGameID": 10060, "timestamp": 4049, "targetID": 27},
             {"type": "cast", "abilityGameID": 10060, "timestamp": 126236, "targetID": 27},  # on themselves: kept
             {"type": "cast", "abilityGameID": 2061, "timestamp": 4100, "targetID": 27}]
    assert [c["timestamp"] for c in without_twins(casts, 27)] == [4027, 126236, 4100]


def test_the_twins_go_from_an_existing_corpus(tmp_path):
    from paf.corpus import db

    con = db.connect(tmp_path / "c.sqlite")
    con.execute("PRAGMA user_version=0")
    con.executemany("INSERT INTO player_cast(report, fight_id, actor_id, ability_id, type, t, target_id) "
                    "VALUES ('r',1,27,10060,'cast',?,?)", [(4.027, 11), (4.049, 27), (126.2, 27)])
    con.commit()
    con.close()
    con = db.connect(tmp_path / "c.sqlite")
    assert [r[0] for r in con.execute("SELECT t FROM player_cast ORDER BY t")] == [4.027, 126.2]
