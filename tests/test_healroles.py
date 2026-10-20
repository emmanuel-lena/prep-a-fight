"""Healing compositions and roles (paf.healroles, issue #27), on WCL answers shaped as the real ones."""
import sqlite3

from paf import healroles
from paf.corpus.db import SCHEMA


def _answer():
    heal = {"entries": [
        {"id": 10, "name": "Monk", "icon": "Monk-Mistweaver", "total": 400, "overheal": 100},
        {"id": 13, "name": "Pri", "icon": "Priest-Holy", "total": 600, "overheal": 600},
        {"id": 8, "name": "Ele", "icon": "Shaman-Elemental", "total": 50, "overheal": 0}]}  # not a healer
    tgt = {"entries": [{"name": "Tank", "icon": "Druid-Guardian", "sources": [{"name": "Monk", "total": 200},
                                                                           {"name": "Pri", "total": 60}]},
                       {"name": "Dps", "icon": "Mage-Arcane", "sources": [{"name": "Pri", "total": 300}]}]}
    disp = {"entries": [{"entries": [{"name": "Essence Rend", "details": [{"id": 10, "total": 3}]}]}]}
    dg = {"series": [{"name": "A", "type": "Mage", "data": [10, 10, 40, 10]},
                     {"name": "B", "type": "Priest", "data": [10, 10, 40]}]}  # a shorter series: no truncation
    hg = {"series": [{"name": "Monk", "type": "Monk", "data": [100, 100, 100, 100]},
                     {"name": "Pri", "type": "Priest", "data": [0, 0, 600, 0]}]}
    return {"heal": {"data": heal}, "tgt": {"data": tgt}, "disp": {"data": disp}, "deaths": {"data": {"entries": [1]}},
            "hg": {"data": hg}, "dg": {"data": dg}}


def test_one_kill_read_from_the_tables_and_graphs():
    rows, deaths, share = healroles.kill_stats(_answer())
    by = {r[0]: r for r in rows}
    assert set(by) == {10, 13} and deaths == 1 and share == 0.25  # one point of four is a spike
    assert by[10][5] == 200 and by[13][5] == 60  # healing on the tank, by name
    assert by[10][6] == 0.25 and by[13][6] == 1.0  # share of their healing in the spike
    assert by[10][7] == 3 and by[13][7] == 0  # dispels


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    healroles.ensure_tables(con)
    return con


def test_compositions_and_jobs():
    con = _db()
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status, duration_s) "
                    "VALUES (?,1,3470,4,'done',240)", (rep,))
        healers = [("Shaman", "Restoration"), ("Priest", "Holy")] + ([("Druid", "Restoration")] if k < 6 else [])
        for i, (cls, spec) in enumerate(healers + [("Mage", "Arcane")]):
            con.execute("INSERT INTO player VALUES (?,1,?,?,?,300,0)", (rep, i, cls, spec))
        con.execute("INSERT INTO heal_kill VALUES (?,1,?,0.2)", (rep, k % 3))
        # the shaman heals the spikes, the priest gives Power Infusion to a dps every kill
        con.executemany("INSERT INTO heal_stat VALUES (?,1,?,?,?,?,?,?,?,?)", [
            (rep, 0, "Shaman", "Restoration", 100, 30, 10, 0.5, 0), (rep, 1, "Priest", "Holy", 100, 60, 10, 0.25, 0)]
            + ([(rep, 2, "Druid", "Restoration", 100, 60, 10, 0.25, 0)] if k < 6 else []))
        con.execute("INSERT INTO heal_cast VALUES (?,1,1,10060,?,1)", (rep, 120 + k))
        con.execute("INSERT INTO heal_cast VALUES (?,1,0,98008,?,0)", (rep, 30 + k))  # Spirit Link
    cs = healroles.comps(con, 3470, 4, min_kills=1)
    assert [(c.label, c.kills) for c in cs] == [("Holy Priest + Restoration Druid + Restoration Shaman", 6),
                                               ("Holy Priest + Restoration Shaman", 4)]
    assert cs[0].deaths == 1.0 and cs[0].duration == 240
    pres = {p.spec: p for p in healroles.presence(con, 3470, 4)}
    assert pres["Restoration Druid"].share == 0.6 and pres["Restoration Shaman"].share == 1.0
    assert pres["Restoration Druid"].deaths_with == 1 and pres["Restoration Druid"].deaths_without == 0.8  # a mean now
    rs = {r.spec: r for r in healroles.roles(con, 3470, 4, {10060: "Power Infusion", 98008: "Spirit Link Totem"},
                                             min_players=5)}
    shaman, priest = rs["Restoration Shaman"], rs["Holy Priest"]
    assert any("spikes: 50%" in j for j in shaman.jobs) and any("wastes little" in j for j in shaman.jobs)
    assert any("externals: 1.0" in j for j in priest.jobs)
    assert priest.cd_names == [("Power Infusion", 1.0, [124.5])]
    assert rs["Restoration Druid"].jobs == ["close to the other healers on every number below"]


def test_a_healer_who_never_attacks_is_still_counted():
    """The corpus' players come from the damage table: the healers' compositions come from the healing tables."""
    con = _db()
    con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status, duration_s) "
                "VALUES ('r',1,3470,4,'done',240)")
    con.execute("INSERT INTO player VALUES ('r',1,9,'Mage','Arcane',300,10)")  # no healer in the damage table
    con.execute("INSERT INTO heal_kill VALUES ('r',1,0,0.2)")
    con.executemany("INSERT INTO heal_stat VALUES ('r',1,?,?,?,100,30,10,0.3,0)",
                    [(1, "Paladin", "Holy"), (2, "Evoker", "Preservation")])
    assert [c.label for c in healroles.comps(con, 3470, 4, min_kills=1)] == ["Holy Paladin + Preservation Evoker"]


def test_waves_are_the_moments_without_a_big_hit():
    """Vashnik heroic (2026-10-20): no spike at x1.6 the median raid damage, waves at x1.3: the three highest are
    the moments (the sheet said "no big moment: steady raid damage" under a curve of waves)."""
    from paf import healer

    curve = [10, 10, 13, 10, 10, 10, 12.5, 10, 10, 10, 13.5, 10, 10, 10, 12.2, 10, 10, 10]
    found = healer.moments(curve, [])
    assert [round(m.ratio, 2) for m in found] == [1.3, 1.25, 1.35]
    assert max(m.ratio for m in found) < healer.SPIKE


def test_a_wave_is_named_after_the_cast_before_it():
    """Vashnik heroic: Imbibe at 0:24, 1:48 and 3:12, the raid's waves at 0:40, 2:10 and 3:40 (16 to 28 s later):
    each wave reads "after Imbibe", matched by timing; a cast within 8 s still names a hit directly."""
    from paf import healer

    curve = [10.0] * 50
    for t in (40, 130, 220):
        curve[int(t // healer.STEP)] = 13.0
    found = healer.moments(curve, [("Imbibe", [24.0, 108.0, 192.0])])
    assert [m.boss_spell for m in found] == ["after Imbibe"] * 3
    assert healer.moments(curve, [("Soulcoil Ignition", [36.0])])[0].boss_spell == "Soulcoil Ignition"


def test_what_the_top_healers_dispel_is_measured():
    """Vashnik heroic (2026-10-20): no ability is dispellable in the game data, yet the top Restoration Shamans
    dispel Exploding Infection about 4 times a kill: the sheet says what they remove, from their dispel events."""
    import sqlite3

    from paf import healroles
    from paf.corpus.db import SCHEMA

    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    healroles.ensure_tables(con)
    for k in range(2):
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 4, 250, 'done')", (f"r{k}",))
        con.execute("INSERT INTO ranked(report, fight_id, spec, actor_id) VALUES(?, 1, 'Restoration', 7)", (f"r{k}",))

    class Client:
        def query(self, *a, **k):
            return {"reportData": {"report": {"fights": [{"startTime": 0, "endTime": 250000}]}}}

        def events(self, *a, **k):
            return [{"type": "dispel", "extraAbilityGameID": 1}] * 4 + [{"type": "dispel", "extraAbilityGameID": 2}]

    assert healroles.fetch_dispels(Client(), con, 9, 4) == 2
    got, n = healroles.dispelled(con, 9, 4, {1: "Exploding Infection", 2: "Congealing Bolt"})
    assert n == 2 and got == [("Exploding Infection", 4.0), ("Congealing Bolt", 1.0)]
