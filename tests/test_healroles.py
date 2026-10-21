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


KINDS = {10060: "damage", 47788: "protective", 322109: ""}  # paf.gamedata.external_kind on the 12.1 game data


def test_compositions_and_jobs(monkeypatch):
    monkeypatch.setattr(healroles, "external_kind", lambda ab: KINDS.get(ab, ""))
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
        if k % 2:  # Guardian Spirit on a player every other kill; Touch of Death on the boss is no external
            con.execute("INSERT INTO heal_cast VALUES (?,1,1,47788,?,1)", (rep, 200 + k))
        con.execute("INSERT INTO heal_cast VALUES (?,1,0,322109,?,1)", (rep, 220 + k))
        con.execute("INSERT INTO heal_cast VALUES (?,1,0,98008,?,0)", (rep, 30 + k))  # Spirit Link
    monkeypatch.setattr(healroles, "DEATH_KILLS", 1)  # ten kills here; the sheets need 15 with their deaths read
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
    assert shaman.jobs == ["nothing stands out against the other healers"]  # 10 kills: under JOB_KILLS
    # Power Infusion is a damage dealer's buff, said last; Guardian Spirit the protective external
    assert priest.externals == 0.5 and priest.buffs == 1.0 and priest.buff_spells == ["Power Infusion"]
    assert priest.jobs == ["nothing stands out against the other healers"]  # a buff is no healing job
    assert not [c for c in priest.cd_names if c[0] == "Power Infusion"]  # cast on another player: off the cards
    assert shaman.externals == 0 and shaman.raid_cds == 2.0  # Spirit Link, and Touch of Death on the boss
    assert rs["Restoration Druid"].jobs == ["nothing stands out against the other healers"]


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

        def events(self, *a, data_type="All", **k):  # each Exploding Infection removed 4 s after it lands
            if data_type == "Debuffs":
                return [{"type": "applydebuff", "abilityGameID": 1, "targetID": 30 + i,
                         "timestamp": 1000 * (10 + 50 * i)} for i in range(4)]
            return [{"type": "dispel", "extraAbilityGameID": 1, "targetID": 30 + i, "timestamp": 1000 * (14 + 50 * i)}
                    for i in range(4)] + [{"type": "dispel", "extraAbilityGameID": 2, "timestamp": 99000}]

    assert healroles.fetch_dispels(Client(), con, 9, 4) == 2
    names = {1: "Exploding Infection", 2: "Congealing Bolt"}
    got, n = healroles.dispelled(con, 9, 4, names)
    assert n == 2 and got == [("Exploding Infection", 4.0), ("Congealing Bolt", 1.0)]
    assert healroles.dispel_delay(con, 9, 4, "Exploding Infection", names) == (4.0, 8)
    assert healroles.dispel_delay(con, 9, 4, "Congealing Bolt", names) is None  # not timed: only the most removed


def test_power_infusion_is_no_job_of_the_boss():
    """Nek'zali heroic (2026-10-20): the Holy Priest's only job was Power Infusion, given on every boss."""
    from paf.healer import jobs_lead

    priest = healroles.Role("Holy Priest", 40, 0.2, 0.07, 0.2, 0.4, 0.6, 3, 0, jobs=[
        "buffs a damage dealer: Power Infusion 2.1 a kill"])
    shaman = healroles.Role("Restoration Shaman", 40, 0.2, 0.07, 0.2, 0.2, 0.6, 3, 0, jobs=[
        "answers the raid's damage spikes: 26% of its healing lands in them (the other healers 18%)"])
    assert jobs_lead([priest, shaman], "Holy Priest") == (
        "<p class='lead'>Your spec here: nothing stands out against the other healers of the same kills. "
        "The others: the Restoration Shaman answers the raid&#x27;s damage spikes: 26% of its healing lands in them "
        "(the other healers 18%). A job is read kill by kill, against the other healers of that kill; the table "
        "below shows each spec&#x27;s median player, so its numbers differ.</p>")


def test_a_cooldown_pressed_as_soon_as_it_is_back_answers_no_hit():
    """Power Infusion "2:07 · the 2:10 hit" (Vashnik): pressed every 2 minutes, 3 times in 4:45, it lands near a hit
    by its cadence. Divine Hymn, twice in 4:45 on a 2-minute gap, is kept for moments."""
    from paf.healroles import on_cadence

    pi = [[3.0, 127.0, 252.0] for _ in range(8)]
    assert 120 <= on_cadence(pi, 3.0, 285.0) <= 130
    hymn = [[4.0, 71.0 + 30 * (i % 3)] for i in range(8)]
    assert on_cadence(hymn, 2.0, 285.0) == 0.0


def test_a_cooldown_kept_past_the_pull_is_chosen():
    """Restoration Druid, Nek'zali: Tranquility at 0:35 (the hit) and 3:55 read "on cooldown"; kept past the pull,
    the first press is a choice."""
    from paf.healroles import on_cadence

    assert on_cadence([[35.0, 235.0] for _ in range(8)], 2.0, 278.0) == 0.0


def test_deaths_need_enough_kills_with_their_deaths(monkeypatch):
    """Vashnik tank: "Protection Paladin 1.3 deaths" came from 6 kills with deaths read (40 of the 100 had them)."""
    from paf import healroles

    monkeypatch.setattr(healroles, "kills_of", lambda *a, **k: {
        i: ((("Protection Paladin",) if i < 18 else ()), 250.0, (1 if i < 6 else None) if i < 18 else 2)
        for i in range(60)})
    pal = next(p for p in healroles.presence(None, 1, 4) if p.spec == "Protection Paladin")
    assert pal.kills == 18 and pal.deaths_with is None and pal.deaths_without == 2.0


def test_a_dropped_caster_is_no_third_spec(monkeypatch):
    """Mistweaver corpus, Nek'zali: a priest under 3% of the healing was dropped from the healers, its casts kept with
    no spec; Power Infusion then had three "specs" (Holy, Discipline and none), read as a trinket, and left the
    Holy Priest card."""
    monkeypatch.setattr(healroles, "external_kind", lambda ab: "damage" if ab == 10060 else "")
    con = _db()
    for k in range(10):
        rep = f"r{k}"
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status, duration_s) "
                    "VALUES (?,1,3470,4,'done',240)", (rep,))
        con.execute("INSERT INTO heal_kill VALUES (?,1,0,0.2)", (rep,))
        con.executemany("INSERT INTO heal_stat VALUES (?,1,?,?,?,?,?,?,?,?)", [
            (rep, 0, "Priest", "Holy", 100, 30, 10, 0.3, 0), (rep, 1, "Priest", "Discipline", 100, 30, 10, 0.3, 0),
            (rep, 2, "Priest", "Holy", 1, 0, 0, 0.0, 0)])  # under 3%: no healer of the kill
        for actor in (0, 1, 2):
            con.execute("INSERT INTO heal_cast VALUES (?,1,?,10060,120,1)", (rep, actor))
    rs = {r.spec: r for r in healroles.roles(con, 3470, 4, {10060: "Power Infusion"}, min_players=5)}
    assert rs["Holy Priest"].buffs == 1.0 and rs["Holy Priest"].buff_spells == ["Power Infusion"]


def test_a_job_is_paired_within_the_kill_and_leaves_the_ranked_healer_out():
    """The jobs audit (2026-10-20), Vashnik heroic: Holy Priests dispel 1.4 times a minute against 0.8 for the other
    healers of the same kills; the corpus' ranked healer is left out (its kills were picked for it)."""
    per_kill, durs = {}, {}
    for k in range(30):
        key = (f"r{k}", 1)
        durs[key] = 240.0
        per_kill[key] = [
            (key[0], 1, 0, "Priest", "Holy", 100, 30, 8, 0.2, 5 + k % 3),      # 1.25-1.75 a minute
            (key[0], 1, 1, "Shaman", "Restoration", 100, 30, 8, 0.2, 3 + k % 2),  # 0.75-1.0
            (key[0], 1, 2, "Paladin", "Holy", 300, 30, 30, 0.2, 9),            # the ranked healer: left out
            (key[0], 1, 3, "Paladin", "Holy", 100, 30, 8, 0.2, 3)]
    found = healroles.paired_jobs(per_kill, durs, ("Paladin", "Holy"))
    assert list(found) == ["Holy Priest"]
    assert found["Holy Priest"] == ["dispels more: 1.5 times a minute, against 0.8 for the other healers of the same "
                                    "kills (30 kills)"]
    assert healroles.paired_jobs(dict(list(per_kill.items())[:15]), durs, ("Paladin", "Holy")) == {}  # too few


def test_jobs_pool_every_corpus_kill_once_without_its_ranked_players(tmp_path):
    """The sheets of a boss say the same jobs: every corpus' kills of the boss, each once, its ranked players left
    out (a collected kill names it; a pending one stands it in with its best healer of the ranked spec)."""
    def corpus(name, kills, ranked):
        con = sqlite3.connect(tmp_path / name)
        con.executescript(SCHEMA)
        healroles.ensure_tables(con)
        for rep, status in kills:
            con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status, duration_s) "
                        "VALUES (?,1,3455,4,?,240)", (rep, status))
            con.executemany("INSERT INTO heal_stat VALUES (?,1,?,?,?,?,?,?,?,?)", [
                (rep, 0, "Priest", "Holy", 300, 30, 8, 0.2, 6), (rep, 1, "Priest", "Holy", 100, 30, 8, 0.2, 5),
                (rep, 2, "Shaman", "Restoration", 100, 30, 8, 0.2, 3)])
        for rep, cls, spec, aid in ranked:
            con.execute("INSERT INTO ranked(report, fight_id, class, spec, actor_id) VALUES (?,1,?,?,?)",
                        (rep, cls, spec, aid))
        con.commit()
        con.close()
        return tmp_path / name

    a = corpus("corpus-priest-holy.sqlite", [("r1", "done"), ("r2", "pending")],
               [("r1", "Priest", "Holy", 1), ("r2", "Priest", "Holy", None)])
    b = corpus("corpus-warrior-protection.sqlite", [("r1", "done"), ("r3", "done")],
               [("r1", "Warrior", "Protection", 9), ("r3", "Warrior", "Protection", 9)])
    per_kill, durs, _cover, _casts, _top, _whole = healroles.pooled_kills(3455, 4, [a, b])
    assert sorted(per_kill) == [("r1", 1), ("r2", 1), ("r3", 1)] and durs[("r3", 1)] == 240
    assert [h[2] for h in per_kill[("r1", 1)]] == [0, 2]  # each healer once, the ranked Holy Priest (actor 1) out
    assert [h[2] for h in per_kill[("r2", 1)]] == [1, 2]  # pending: its best Holy Priest (actor 0) stands it in
    assert [h[2] for h in per_kill[("r3", 1)]] == [0, 1, 2]  # a tank's kill: every healer kept


def test_a_moment_is_said_where_most_press_it():
    # Preservation Evoker, Nek'zali (round 31): Rewind at 1:10-1:14 for 26, 1:20-1:24 for 22: "1:16" was the median
    lists = [[70.0 + k % 5] for k in range(26)] + [[80.0 + k % 5] for k in range(22)] + [[] for _ in range(52)]
    times, _alt, _of = healroles.press_moments(lists, 1)
    assert 70 <= times[0] <= 74


def test_a_job_is_checked_on_the_ranked_players():
    # Vashnik (round 38): the average Holy Priest dispels 1.4 a minute against 0.8, the ranked ones as the others
    durs = {(f"r{k}", 1): 240.0 for k in range(30)}
    top = ([(f"r{k}", 1, 0, "Priest", "Holy", 100, 30, 8, 0.2, 4) for k in range(15)]
           + [(f"r{k}", 1, 1, "Paladin", "Holy", 100, 30, 8, 0.2, 4) for k in range(15, 30)])
    assert healroles._top_check(top, durs, "Holy Priest", "dispels") == (
        "; the top players ranked by their healing do not: the top Holy Priests 1.0, the other specs' top "
        "healers 1.0 (15 and 15 players)")
    top = [(*h[:9], 8 if h[3] == "Priest" else 4) for h in top]  # 2.0 against 1.0: it holds, nothing said
    assert healroles._top_check(top, durs, "Holy Priest", "dispels") == ""
