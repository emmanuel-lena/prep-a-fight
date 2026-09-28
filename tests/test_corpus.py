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
