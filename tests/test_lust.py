"""Bloodlust spots (paf.corpus.lust): the raid's lust read on every player, grouped into spots."""
import sqlite3

from paf.corpus.db import SCHEMA
from paf.corpus.lust import default_lust, kill_lust, kill_spot, lust_spots


def _buffs(kind_times, ability=2825, players=12):
    return [{"abilityGameID": ability, "type": kind, "targetID": p, "timestamp": 1_000_000 + t * 1000}
            for p in range(players) for kind, t in kind_times]


def test_a_lust_reaches_the_whole_raid_and_lasts():
    start, end = 1_000_000, 1_000_000 + 300_000
    assert kill_lust(_buffs([("applybuff", 95.0), ("removebuff", 135.0)]), start, end) == 95.0
    # cast before the pull: the buffs only end, 40 s in
    assert kill_lust(_buffs([("removebuff", 39.0)]), start, end) == 0.0
    # a 2 s Time Warp proc on a few players is not a lust; the real one comes later
    proc = _buffs([("applybuff", 5.0), ("removebuff", 7.0)], ability=80353, players=3)
    assert kill_lust(proc + _buffs([("applybuff", 200.0)], ability=32182), start, end) == 200.0
    assert kill_lust(proc, start, end) is None


def test_a_kills_lust_falls_in_a_spot():
    phases = [("Stage One", 0.0), ("Intermission", 148.7), ("Stage Two", 252.9)]
    assert kill_spot(2.0, phases, 380.0)[0] == "pull"
    assert kill_spot(260.0, phases, 380.0) == ("phase", "Stage Two", 7.1)
    assert kill_spot(340.0, phases, 380.0)[0] == "last_minute"
    assert kill_spot(200.0, phases, 380.0)[0] == "time"


def test_spots_of_the_top_raids():
    """Nek'zali mythic: half the top raids lust on pull, the others at the start of Stage Two (whenever it comes)."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for k in range(20):
        rep, s2 = f"r{k}", 240.0 + 2 * k
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status, duration_s) "
                    "VALUES (?,1,3470,5,'done',?)", (rep, s2 + 130))
        con.executemany("INSERT INTO phase VALUES (?,1,?,?,0,?)",
                        [(rep, 1, "Stage One", 0.0), (rep, 2, "Stage Two", s2)])
        t = 0.0 if k < 10 else s2 + 5 if k < 18 else None
        con.execute("INSERT INTO raid_lust VALUES (?,1,?)", (rep, t))
    spots = lust_spots(con, 3470, 5, [("Stage One", 0.0), ("Stage Two", 259.0)], 389.0)
    assert [(s.label, s.kills, s.t) for s in spots] == [("On pull", 10, 0.0), ("Start of Stage Two", 8, 264.0),
                                                       ("No Bloodlust", 2, None)]
    assert default_lust(spots) == 0.0


def test_the_sheet_says_where_bloodlust_goes_and_what_the_other_spots_give():
    from paf.corpus.lust import Spot
    from paf.prep_report import PrepData, lust_line

    pull = Spot("pull", "On pull", 0.52, 52, 0.0)
    s2 = Spot("phase", "Start of Stage Two: Uncoiling", 0.40, 40, 262.0, "Stage Two: Uncoiling", 4.0)
    d = PrepData("Nek'zali", "mythic", "Elemental", "Char", lust=0.0)
    d.goal = "total"
    d.lust_spots = [(pull, 0.0, 0.0), (s2, 1.24, 0.8)]
    d.lust_noise = 0.3
    line = lust_line(d)
    assert line == ("<b>Bloodlust on pull</b> (52% of the top raids lust there). Lust at the start of Stage Two: "
                    "Uncoiling (40% of them) would give you <b class='pos'>+1.2% damage</b> (&plusmn;0.3%): tell your "
                    "raid lead.")
    assert lust_line(d, True).startswith("<span class='act'><b>Bloodlust</b> <span class='pill'>at the pull</span>"
                                         "<span class='pill'>52% of the top raids</span></span> Lust at the start")
    d.lust_pick, d.lust = s2.label, 262.0
    assert lust_line(d) == ("<b>Bloodlust at 4:22</b>, the start of Stage Two: Uncoiling (your raid lead's pick). "
                            "The top raids' other spots give you no more.")
    d.lust_spots = [(pull, 0.0, 0.0), (s2, 0.2, 0.1)]
    d.lust_pick, d.lust = "", 0.0
    assert lust_line(d).endswith("The top raids' other spots give you no more.")  # within the noise


def test_the_raid_lead_picks_a_spot():
    from paf import raidlead
    from paf.corpus.lust import Spot

    pull = Spot("pull", "On pull", 0.52, 52, 0.0)
    s2 = Spot("phase", "Start of Stage Two", 0.40, 40, 262.0, "Stage Two", 4.0)
    sh = {"boss": "Nek'zali", "targets": [], "builds": [], "enc": 3470, "diff": 5, "lust": [pull, s2],
          "lust_pick": "", "lust_kills": 100,
          "lust_gains": ("Elemental", {"On pull": [0.0, 0.0], "Start of Stage Two": [1.24, 0.8]}, 0.3, 389.8)}
    assert raidlead.lust_spot(sh) is pull  # no pick: the top raids' most used spot
    html = raidlead.lust_block(sh, "mythic")
    assert "value='On pull' checked" in html and "+1.2%<small>&plusmn;0.3%</small>" in html and ">baseline<" in html
    assert "<b>Start of Stage Two, <span class='t'>4:22</span></b>" in html
    assert "8% of the top raids lust elsewhere" in html
    assert "Lust at the start of Stage Two: +1.2% damage for the Elemental prep over lust on pull." in html
    assert "The top raids are split: 52% on pull, 40% at the start of Stage Two." in html
    assert "(6:29 kill)" in html
    assert "Bloodlust: on pull" in raidlead.text(sh, "mythic")
    sh["lust_pick"] = "Start of Stage Two"
    assert raidlead.lust_spot(sh) is s2 and "value='Start of Stage Two' checked" in raidlead.lust_block(sh, "mythic")
