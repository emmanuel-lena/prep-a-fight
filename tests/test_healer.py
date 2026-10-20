import json
import sqlite3
from types import SimpleNamespace

from paf import healer
from paf.corpus.db import SCHEMA


def test_raid_damage_curve_and_its_big_moments():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for k in range(3):  # 60 s kills, 2 players, a burst at 30 s
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 4, 60, 'done')", (f"r{k}",))
        base = [100.0] * 12
        base[6] = 500.0  # 30-35 s
        healer.ensure_table(con)
        con.execute("INSERT INTO raid_damage VALUES(?, 1, 5.0, ?)", (f"r{k}", json.dumps({"A": base, "B": base})))
    curve = healer.raid_curve(con, 9, 4, 60.0)
    assert curve[0] == 200.0 and curve[6] == 1000.0
    found = healer.moments(curve, [("Venom Burst", [27.0]), ("Far Away", [5.0])])
    assert [(m.t, m.boss_spell) for m in found] == [(30.0, "Venom Burst")] and round(found[0].ratio) == 5


def test_cooldowns_where_the_top_healers_press_them():
    ab = SimpleNamespace(id=1, name="Spirit Link Totem", users=0.9, per_kill=2.0)
    rare = SimpleNamespace(id=2, name="Healing Wave", users=1.0, per_kill=80.0)  # spammed: not a cooldown
    players = [{"casts": {1: [29.0, 150.0]}} for _ in range(5)]
    tl = SimpleNamespace(abilities=[ab, rare], duration=240.0, players=players)
    found = [healer.Moment(30.0, 1000.0, 5.0, "Venom Burst")]
    cds = healer.cooldowns(tl, found, {1: (180.0, 1), 2: (0.0, 1)})
    assert [c.name for c in cds] == ["Spirit Link Totem"]
    assert cds[0].times == [29.0, 150.0] and cds[0].near == ["0:30 Venom Burst", ""]
    h = healer.HealerPrep("Boss", "heroic", "Restoration Shaman", 5, 240.0, [100.0] * 48, found, cds,
                          [(3, "top build A", "ABC")], [("Trinket", 1, 0.5)], ["Dispel the poison."], [])
    page = healer.render(h)
    assert "Your healing cooldowns" in page and "Spirit Link Totem" in page and "QE Live" in page
    assert "data-copy='ABC'" in page and "Dispel the poison." in page


def test_two_habits_are_not_one_plan():
    """Holy Paladin, Vashnik heroic: Avenging Wrath "0:21, 0:41", a 2-minute cooldown pooled over players who press
    it at 0:21 and others at 0:41."""
    ab = SimpleNamespace(id=1, name="Avenging Wrath", users=0.9, per_kill=2.0)
    players = [{"casts": {1: [21.0, 150.0]}} for _ in range(5)] + [{"casts": {1: [41.0, 165.0]}} for _ in range(4)]
    tl = SimpleNamespace(abilities=[ab], duration=240.0, players=players)
    cd = healer.cooldowns(tl, [], {1: (120.0, 1)})[0]
    assert cd.times[0] == 21.0 and 41.0 in cd.alt and all(t - 21.0 >= 100 for t in cd.times[1:])


def test_a_moment_is_named_by_what_hits_the_raid():
    """Nek'zali heroic, 0:35: the healer sheets said "Possession Barrage, aimed at the tank" (the cast just before);
    the damage taken by ability says Soulcoil Rite 53%, Possession Barrage 31%."""
    found = [healer.Moment(35.0, 1.6e6, 1.6), healer.Moment(75.0, 1.7e6, 1.7), healer.Moment(200.0, 1e6, 1.5)]
    by = {"Soulcoil Rite": [0.0] * 7 + [53, 0] + [0.0] * 6 + [75, 0] + [0.0] * 24 + [32, 0],
          "Possession Barrage": [0.0] * 7 + [31, 0] + [0.0] * 6 + [6, 0] + [0.0] * 24 + [31, 0],
          "Corpse Blight": [0.0] * 7 + [16, 0] + [0.0] * 6 + [19, 0] + [0.0] * 24 + [37, 0]}
    healer.name_by_damage(found, by)
    assert [m.boss_spell for m in found] == [
        "Soulcoil Rite and Possession Barrage", "Soulcoil Rite",
        "mixed damage, most from Corpse Blight and Soulcoil Rite"]


def test_two_hits_near_the_same_height_are_both_kept():
    """Preservation Evoker's corpus, Nek'zali heroic: 0:35 x1.62 and 1:20 x1.57; a line at x1.6 kept one only, the
    other healer sheets of the same boss both."""
    curve = [100.0] * 60
    curve[7], curve[16] = 162.0, 157.0
    assert [m.t for m in healer.moments(curve, [])] == [35.0, 80.0]


def test_every_cast_a_kill_is_said():
    """Holy Priest, Nek'zali: Divine Hymn "2.0 a kill" showed one moment; the second press is said, without a time."""
    ab = SimpleNamespace(id=1, name="Divine Hymn", users=1.0, per_kill=2.0)
    players = [{"casts": {1: [4.0, 60.0 + 25 * i]}} for i in range(8)]  # the 2nd spread over three minutes
    tl = SimpleNamespace(abilities=[ab], duration=280.0, players=players)
    cd = healer.cooldowns(tl, [], {1: (180.0, 1)})[0]
    assert cd.times == [4.0] and "+1 more when they need it" in healer.cooldowns_html([cd])


def test_no_moment_after_the_kill():
    """Vashnik tank: Rallying Cry "4:32" in a 4:21 fight."""
    ab = SimpleNamespace(id=1, name="Rallying Cry", users=1.0, per_kill=1.0)
    tl = SimpleNamespace(abilities=[ab], duration=261.0, players=[{"casts": {1: [272.0]}} for _ in range(6)])
    assert healer.cooldowns(tl, [], {1: (180.0, 1)})[0].times == []


def test_a_stretch_without_a_break_is_said():
    """A stretch the raid takes 1.15x its median damage or more for 30 s or more has no peak and is still a healing
    check. Nek'zali's Stage Two (about 1.05x, measured) is not one."""
    curve = [100.0] * 40 + [125.0] * 8 + [100.0] * 10
    assert healer.sustained(curve) == [(200.0, 240.0, 1.25)]
    assert healer.sustained([100.0] * 40 + [105.0] * 18) == []
