import sqlite3

from paf.corpus.analyze import council
from paf.corpus.db import SCHEMA
from paf.corpus.template import build_template
from paf.fight import Fight

MEMBERS = {1: "Trader", 2: "Sage", 3: "Mate"}


def corpus(shares=(36, 33, 31)):
    """Ten kills of a three-boss council: the ranked player hits Trader for 60 s, then Sage, then Trader again."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for gid, name in MEMBERS.items():
        con.execute("INSERT INTO npc VALUES(?, ?, 1)", (gid, name))
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 5, 200, 'done')", (rep,))
        con.execute("INSERT INTO ranked(report, fight_id, spec, actor_id) VALUES(?, 1, 'Elemental', 7)", (rep,))
        for gid, name in MEMBERS.items():
            con.execute("INSERT INTO npc_actor VALUES(?, ?, ?)", (rep, 100 + gid, gid))
            con.execute("INSERT INTO damage_by_target VALUES(?, 1, 7, ?, ?)", (rep, name, shares[gid - 1]))
            # the members' windows on the damage graph: what used to become adds
            con.execute("INSERT INTO unit_window VALUES(?, 1, ?, 0, 200, 1.0)", (rep, name))
        for t in range(0, 200, 2):
            target = 101 if t < 60 or t >= 160 else 102
            con.execute("INSERT INTO player_cast(report, fight_id, actor_id, ability_id, type, t, target_id) "
                        "VALUES(?, 1, 7, 188196, 'cast', ?, ?)", (rep, t, target))
    return con


def test_a_council_is_one_target_with_a_focus_order(monkeypatch):
    monkeypatch.setattr("paf.corpus.template.game_amp", lambda *a: (None, ""))
    con = corpus()
    assert council(con, 9, 5) == ["Trader", "Sage", "Mate"]
    fight, _ = build_template(con, 9, 5, "Trader", "Elemental", "mythic", title="The Explorers")
    assert fight.add_waves == [] and fight.vulnerable == [] and fight.invulnerable == []
    assert [(f.start, f.duration, f.name, f.support) for f in fight.focus] == [
        (0, 60, "Trader", 1.0), (60, 100, "Sage", 1.0), (160, 40, "Trader", 1.0)]
    assert not any(line.startswith("raid_events") and "adds" in line for line in fight.to_simc())
    assert Fight.from_dict(__import__("dataclasses").asdict(fight)).focus == fight.focus


def test_a_boss_with_a_helper_is_not_a_council():
    assert council(corpus(shares=(64, 34, 2)), 9, 5) == []  # The Coiled Altar: Zul'jan takes most of it
    assert council(corpus(shares=(80, 10, 10)), 9, 5) == []


def test_stacked_members_from_direct_damage():
    from paf.corpus.units import stacked_targets

    hits = [{"type": "damage", "timestamp": 1000 + t * 1000, "targetID": tid}
            for t in range(0, 30, 3) for tid in (101, 102)]  # a Chain Lightning on two members every 3 s
    hits += [{"type": "damage", "timestamp": 1000 + t * 1000, "targetID": 103, "tick": True} for t in range(30)]
    assert stacked_targets(hits, {101, 102, 103}, 1000) == 2  # the dot on the third one does not count


def test_stacked_council_is_simulated_as_several_bosses(monkeypatch):
    monkeypatch.setattr("paf.corpus.template.game_amp", lambda *a: (None, ""))
    con = corpus()
    con.executemany("INSERT INTO council_stack VALUES(?, 1, ?)", [(f"r{k}", 2.0) for k in range(4)])
    fight, _ = build_template(con, 9, 5, "Trader", "Elemental", "mythic")
    assert fight.targets == 2 and "desired_targets=2" in fight.to_simc()


def test_priority_damage_is_dropped_with_several_bosses(tmp_path):
    import json

    from paf.simc import parse_json

    data = {"sim": {"options": {"desired_targets": 2},
                    "players": [{"collected_data": {"dps": {"mean": 200}, "prioritydps": {"mean": 120}}}],
                    "profilesets": {"metric": "Damage per Second", "results": [
                        {"name": "a", "mean": 210, "additional_metrics": [
                            {"metric": "Damage per Second to Priority Target/Boss", "mean": 130}]}]}}}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(data))
    res = parse_json(path)
    assert "prioritydps" not in res.baseline and "prioritydps" not in res.profilesets[0].metrics


def test_two_bosses_kept_apart_are_one_target(monkeypatch):
    """Entombed Sentinels (heroic, 2026-10-20): two bosses at 50/50, not a council; the top Elementals and Subtlety
    Rogues hit one at a time (6 kills each). The second boss used to be a target beside the first (simulated 1.13
    and 1.31 of the real DPS); kept apart, it is single target (0.89 and 1.00)."""
    from paf.corpus.analyze import boss_units
    from paf.corpus.units import bosses_hit_at_once

    monkeypatch.setattr("paf.corpus.template.game_amp", lambda *a: (None, ""))
    con = corpus(shares=(51, 49, 0))
    assert council(con, 9, 5) == [] and boss_units(con, 9, 5) == ["Trader", "Sage"]
    fight, _ = build_template(con, 9, 5, "Trader", "Elemental", "mythic")
    assert any(w.name.startswith("Sage") for w in fight.add_waves)  # not measured: a target beside the boss
    assert bosses_hit_at_once(con, 9, 5) is None
    con.executemany("INSERT INTO council_stack VALUES(?, 1, ?)", [(f"r{k}", 1.0) for k in range(4)])
    fight, _ = build_template(con, 9, 5, "Trader", "Elemental", "mythic")
    assert not any(w.name.startswith("Sage") for w in fight.add_waves)


def test_a_second_boss_during_the_first_ones_immunity_stays_a_target(monkeypatch):
    """Nek'zali heroic: the top players hit one boss unit at a time because Nek'zali is immune in her intermission
    while the Echo of Jawae is up: the Echo stays a target."""
    monkeypatch.setattr("paf.corpus.template.game_amp", lambda *a: (None, ""))
    con = corpus(shares=(51, 49, 0))
    con.execute("DELETE FROM unit_window WHERE name='Sage'")
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO unit_window VALUES(?, 1, 'Sage', 100, 40, 1.0)", (rep,))
        con.execute("INSERT INTO phase VALUES(?, 1, 1, 'Stage One', 0, 0)", (rep,))
        con.execute("INSERT INTO phase VALUES(?, 1, 2, 'Intermission', 1, 95)", (rep,))
        con.execute("INSERT INTO phase VALUES(?, 1, 3, 'Stage Two', 0, 150)", (rep,))
    con.executemany("INSERT INTO council_stack VALUES(?, 1, ?)", [(f"r{k}", 1.0) for k in range(4)])
    fight, _ = build_template(con, 9, 5, "Trader", "Elemental", "mythic")
    assert [(w.start, w.duration) for w in fight.invulnerable] == [(95, 55)]
    assert any(w.name.startswith("Sage") for w in fight.add_waves)
