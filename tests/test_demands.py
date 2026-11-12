from types import SimpleNamespace

from paf import demands
from paf.corpus import db


def test_a_shield_s_up_and_broken_times_and_its_absorb():
    # Coiled Altar mythic, a top raid (2026-11-12): Veil of Twilight up 230.5 s, broken 242.9 s, 34.8 M
    evs = [{"timestamp": 1000 + 230500, "type": "applybuff", "abilityGameID": 1286912, "targetID": 619,
            "absorb": 34828260},
           {"timestamp": 1000 + 242900, "type": "removebuff", "abilityGameID": 1286912, "targetID": 619, "absorb": 0},
           {"timestamp": 1000 + 500000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 619}]  # still up
    assert demands.shield_events(evs, 1000) == [(1286912, 230.5, 242.9, 34828260.0)]


def test_shield_windows_are_the_typical_occurrences(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    con = db.connect()
    con.executescript(demands.SCHEMA)
    for i, (t0, took) in enumerate([(230, 12), (240, 16), (235, 14)]):
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, kill, status) "
                    "VALUES(?, 1, 7, 5, 1, 'done')", (f"r{i}",))
        con.execute("INSERT INTO enemy_shield VALUES(?, 1, 99, ?, ?, 35e6)", (f"r{i}", t0, t0 + took))
        con.execute("INSERT INTO shield_status VALUES(?, 1)", (f"r{i}",))
    con.execute("INSERT INTO enemy_shield VALUES('r0', 1, 99, 400, 410, 35e6)")  # a 2nd one in one kill of 3: left
    [w] = demands.shield_windows(con, 7, 5, {99: "Veil of Twilight"})
    assert w.kind == "shield" and w.spans == [(235.0, 249.0)]
    assert w.detail == "broken in 14 s by the top raids, 35.0 M absorbed"


def test_the_fight_s_add_bursts_and_amps():
    fight = SimpleNamespace(
        add_waves=[SimpleNamespace(time=35, lifetime=11), SimpleNamespace(time=96, lifetime=11),
                   SimpleNamespace(time=0, lifetime=140)],  # a second boss: no burst
        vulnerable=[SimpleNamespace(start=391, duration=35, multiplier=2)], lust_time=392)
    adds, amp = demands.fight_windows(fight)
    assert adds.spans == [(35, 46), (96, 107)] and adds.detail == "2 waves that live ~11 s"
    assert amp.label == "x2 amp" and amp.detail == "Bloodlust in it"


def test_each_spec_s_damage_in_each_window():
    w = demands.Window("adds", "Add waves", [(1, 3)])
    got = demands.compare([w], {"Subtlety": [1, 10, 10, 1], "Outlaw": [5, 5, 5, 5]})
    assert got == {"Subtlety": {"all": 22, "Add waves": 20}, "Outlaw": {"all": 20, "Add waves": 10}}


def test_the_sheet_says_the_spec_ahead_in_each_window():
    # Twin Fangs mythic, the owner's Rogue: Outlaw +16% on the whole fight, but Subtlety the burst on the adds
    from paf import briefing

    d = SimpleNamespace(specs={"mine": "Subtlety"}, demands={
        "windows": [{"kind": "adds", "label": "Add waves", "spans": [(35, 46)], "detail": "5 waves that live ~11 s"}],
        "damage": {"Subtlety": {"all": 120.7, "Add waves": 38.4}, "Outlaw": {"all": 140.0, "Add waves": 35.6}}})
    html = briefing.demands_html(d)
    assert "What this fight demands" in html and "Add waves</span>" in html
    assert "<td class='pos dm-best'>+16%</td>" in html and "<td class='neg'>-7%</td>" in html
    assert "<td class='dm-me dm-best'>your spec, best</td>" in html
    d.demands["damage"] = {}
    assert "dm-grid" not in briefing.demands_html(d)  # no other spec ticked: the windows only
