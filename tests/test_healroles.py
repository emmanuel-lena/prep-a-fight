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
    assert pres["Restoration Druid"].deaths_with == 1 and pres["Restoration Druid"].deaths_without == 0.5
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
