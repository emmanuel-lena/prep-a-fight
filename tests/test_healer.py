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
        "mostly Corpse Blight and Soulcoil Rite"]


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
    assert cd.times == [4.0] and "+1 more at varying times" in healer.cooldowns_html([cd])


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


def test_one_spell_under_two_ids_is_one_row():
    """Holy Paladin, Nek'zali: Lay on Hands is 633 for some players and 471195 (talented) for others: 54% counting
    one id, about 66% for both."""
    a = SimpleNamespace(id=633, name="Lay on Hands", users=0.4, per_kill=1.0)
    b = SimpleNamespace(id=471195, name="Lay on Hands", users=0.3, per_kill=1.0)
    players = ([{"casts": {633: [80.0]}} for _ in range(4)] + [{"casts": {471195: [82.0]}} for _ in range(3)]
               + [{"casts": {}} for _ in range(3)])
    tl = SimpleNamespace(abilities=[a, b], duration=280.0, players=players)
    cds = healer.cooldowns(tl, [], {633: (420.0, 1), 471195: (420.0, 1)})
    assert [(c.name, round(c.users, 1)) for c in cds] == [("Lay on Hands", 0.7)]


def test_a_held_press_is_not_on_cooldown():
    """Resto Shaman, Nek'zali: the Vessel "3 a kill, 0:03 2:02, on cooldown, about every 97 s": the median gap came
    from the players pressing it 5 times; the shared moments are 2 minutes apart, held."""
    ab = SimpleNamespace(id=7, name="Soulcoiler Ritual Vessel", users=1.0, per_kill=3.0)
    players = ([{"casts": {7: [3.0, 122.0, 214.0]}} for _ in range(8)]
               + [{"casts": {7: [3.0, 95.0, 190.0, 285.0, 380.0]}} for _ in range(8)])
    tl = SimpleNamespace(abilities=[ab], duration=400.0, players=players)
    cd = healer.cooldowns(tl, [], {7: (90.0, 1)})[0]
    gaps = [y - x for x, y in zip(cd.times, cd.times[1:], strict=False)]
    assert cd.every == 0.0 or all(abs(g - cd.every) <= 0.15 * cd.every for g in gaps)


def test_a_channel_s_ticks_do_not_bury_its_cast():
    """Holy Priest, Nek'zali: Divine Hymn's cast (64843) and its ticks (64844, the same name, about 10 a cast) were
    one row, too many casts for a cooldown: the spec's main raid cooldown vanished from the sheet."""
    cast = SimpleNamespace(id=64843, name="Divine Hymn", users=1.0, per_kill=2.0)
    ticks = SimpleNamespace(id=64844, name="Divine Hymn", users=1.0, per_kill=20.0)
    players = [{"casts": {64843: [36.0, 190.0], 64844: [36.0 + i for i in range(10)] + [190.0 + i for i in range(10)]}}
               for _ in range(6)]
    tl = SimpleNamespace(abilities=[cast, ticks], duration=285.0, players=players)
    cds = healer.cooldowns(tl, [], {64843: (180.0, 1), 64844: (0.0, 1)})
    assert [(c.name, c.per_kill) for c in cds] == [("Divine Hymn", 2)]


def test_the_two_sides_of_a_choice_node_are_one_cooldown(monkeypatch):
    """Mistweaver, Nek'zali: "Revival pressed by 61%" and "fewer than half press Restoral (38%)": one talent node,
    pressed by 99% of them."""
    monkeypatch.setattr(healer, "_choice_nodes", lambda: {115310: 7, 388615: 7})
    rev = SimpleNamespace(id=115310, name="Revival", users=0.6, per_kill=1.0)
    res = SimpleNamespace(id=388615, name="Restoral", users=0.4, per_kill=1.0)
    players = [{"casts": {115310: [36.0]}} for _ in range(6)] + [{"casts": {388615: [37.0]}} for _ in range(4)]
    tl = SimpleNamespace(abilities=[rev, res], duration=280.0, players=players)
    cds = healer.cooldowns(tl, [], {115310: (180.0, 1), 388615: (180.0, 1)})
    assert [(c.name, round(c.users, 1)) for c in cds] == [("Revival / Restoral", 1.0)]


def test_one_press_for_either_hit_is_said_once():
    # Nek'zali heroic, Holy Paladin: one Aura Mastery a kill, at 0:36 for some top players, 1:19 for others
    ab = SimpleNamespace(id=1, name="Aura Mastery", users=1.0, per_kill=1.0)
    players = [{"casts": {1: [79.0]}} for _ in range(5)] + [{"casts": {1: [36.0]}} for _ in range(4)]
    tl = SimpleNamespace(abilities=[ab], duration=240.0, players=players)
    found = [healer.Moment(35.0, 1000.0, 5.0, "Soulcoil Rite"), healer.Moment(75.0, 1100.0, 5.0, "Soulcoil Rite")]
    cds = healer.cooldowns(tl, found, {1: (180.0, 1)})
    h = healer.HealerPrep("Boss", "heroic", "Holy Paladin", 9, 240.0, [100.0] * 48, found, cds, [], [], [], [])
    sheet = healer.render_sheet(h)
    # the most shared hit first
    assert "Their Aura Mastery goes on the 1:15 hit (56%, about 1:19) or the 0:35 hit (44%, about 0:36)" in sheet
    assert "for the 1:15 hit, 56% press" not in sheet


def test_two_cooldowns_as_common_for_a_hit_are_both_named():
    # Vashnik heroic, Holy Paladin: Avenging Wrath 36% at 0:42, Aura Mastery 35% at 0:44 for the 0:40 hit
    aw = SimpleNamespace(id=1, name="Avenging Wrath", users=1.0, per_kill=1.0)
    am = SimpleNamespace(id=2, name="Aura Mastery", users=1.0, per_kill=1.0)
    players = [{"casts": {1: [42.0 if i < 36 else 150.0], 2: [44.0 if i < 35 else 170.0]}} for i in range(100)]
    tl = SimpleNamespace(abilities=[aw, am], duration=240.0, players=players)
    found = [healer.Moment(40.0, 1000.0, 5.0, "Caustic Surge")]
    cds = healer.cooldowns(tl, found, {1: (120.0, 1), 2: (180.0, 1)})
    h = healer.HealerPrep("Boss", "heroic", "Holy Paladin", 100, 240.0, [100.0] * 48, found, cds, [], [], [], [])
    sheet = healer.render_sheet(h)
    assert "36% press Avenging Wrath (about 0:42) and 35% press Aura Mastery (about 0:44)" in sheet


def test_the_most_played_build_says_its_side_of_each_split():
    # Disc, Vashnik heroic: the builds scatter on Lightburst, Weal and Woe, Searing Light and a choice node
    names = {1: "Lightburst", 2: "Weal and Woe", 3: "Searing Light", 4: "Protector of the Frail", 5: "Voidwraith"}
    split = [("Lightburst", 0.52), ("Searing Light", 0.47), ("Protector of the Frail 48% / Voidwraith 41%", -1.0)]
    assert (healer._sides({1, 2, 5}, names, split)
            == "of the talents listed below, takes Lightburst and Voidwraith; skips Searing Light")


def test_every_healer_spec_in_one_table():
    # Nek'zali heroic: a Disc's Power Infusion gets its column, a spec without externals a dash
    disc = SimpleNamespace(spec="Discipline Priest", healing=0.22, tank=0.18, spike=0.31, overheal=0.12, dispels=0.9,
                           externals=0.5, buffs=1.4, buff_spells=["Power Infusion"], players=40, jobs=[], cd_names=[])
    shaman = SimpleNamespace(spec="Restoration Shaman", healing=0.27, tank=0.12, spike=0.29, overheal=0.2,
                             dispels=1.1, externals=0.0, buffs=0.0, buff_spells=[], players=38,
                             jobs=["removes Essence Rend"], cd_names=[("Ascendance", 1, [(35.0, 0.38, False)], 0.9)])
    table = healer.roles_table([shaman, disc], "Restoration Shaman")
    assert "<th>Buffs given a kill</th>" in table
    assert "1.4 <small>Power Infusion</small>" in table
    assert "Restoration Shaman <small>(you)</small>" in table and "<small>none</small>" in table
    more = healer.roles_more([shaman, disc], "Restoration Shaman")
    assert "removes Essence Rend" not in more and "Ascendance" not in more  # the lead's jobs; your times: fight tab
    assert "Discipline Priest" in more  # every other spec said, "none shared" too


def test_the_other_healers_cooldowns_on_the_hits_keep_a_button_pressed_on_cooldown():
    # Vashnik heroic (round 29): Tranquility at 0:43 for the 0:40 hit, again at 2:45 as soon as it is back; the
    # list was empty on 13 sheets of 14 when a button pressed on cooldown went whole
    druid = SimpleNamespace(spec="Restoration Druid", jobs=[], cd_names=[
        ("Tranquility", 2.0, [(43.0, 0.42, False), (225.0, 0.24, True)], 0.9)])
    hits = [healer.Moment(40.0, 1000.0, 5.0, "Caustic Surge"), healer.Moment(220.0, 1000.0, 5.0, "Toxic Vapor")]
    more = healer.roles_more([druid], "Holy Priest", hits)
    assert "<b>Tranquility</b> 0:43 &middot; 42%</td>" in more  # the 0:40 hit
    assert "none shared</span></td></tr>" in more  # the 3:40 hit: back from cooldown, no answer


def test_a_press_back_from_cooldown_in_a_hit_is_said_and_drawn_as_none():
    # Vashnik heroic, Restoration Druid: Tranquility at 0:42 for the 0:40 hit, again at 2:45 as soon as it is back
    ab = SimpleNamespace(id=1, name="Tranquility", users=1.0, per_kill=2.0)
    players = [{"casts": {1: [42.0, 165.0]}} for _ in range(10)]
    tl = SimpleNamespace(abilities=[ab], duration=240.0, players=players)
    found = [healer.Moment(40.0, 1000.0, 5.0, "Caustic Surge"), healer.Moment(160.0, 1000.0, 5.0, "Caustic Surge")]
    cds = healer.cooldowns(tl, found, {1: (120.0, 1)})
    assert cds[0].rhythm and cds[0].near[1] == ""
    h = healer.HealerPrep("Boss", "heroic", "Restoration Druid", 10, 240.0, [100.0] * 48, found, cds, [], [], [], [])
    sheet = healer.render_sheet(h)
    assert "100% press Tranquility (about 0:42)" in sheet
    assert ("<span class='none'>None kept</span> (100% press Tranquility in its window, about 2:45&nbsp;&middot;&nbsp;"
            "&#10226;)") in sheet  # the 2:40 hit's row, the legend's glyph as the chips
    assert "2:45 &middot; 5 s after the 2:40 hit starts &middot; 100%&nbsp;&middot;&nbsp;&#10226;</span>" in sheet
    assert "class='cp off'><title>Tranquility 2:45" in sheet and "class='cp'><title>Tranquility 0:42" in sheet


def test_an_external_says_how_many_go_on_another_player():
    # Mistweaver, Nek'zali heroic: about one Life Cocoon in five goes on the Monk himself
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE fight(report TEXT, fight_id INT, encounter_id INT, difficulty INT, status TEXT, cohort TEXT,"
        " duration_s REAL);"
        "CREATE TABLE ranked(report TEXT, fight_id INT, actor_id INT, spec TEXT);"
        "CREATE TABLE player_cast(report TEXT, fight_id INT, actor_id INT, ability_id INT, type TEXT, t REAL,"
        " target_id INT);"
        "INSERT INTO fight VALUES ('a', 1, 3470, 4, 'done', '', 300);"
        "INSERT INTO ranked VALUES ('a', 1, 7, 'Mistweaver');")
    con.executemany("INSERT INTO player_cast VALUES ('a', 1, 7, 116849, 'cast', ?, ?)",
                    [(10.0 * i, 7 if i == 0 else 20 + i) for i in range(5)])
    assert healer.on_others(con, 3470, 4, "Mistweaver", [116849]) == {116849: 0.8}
    cd = healer.Cooldown("Life Cocoon", 116849, 1.0, 4.0, [30.0], [""], why="cast on another player", on_others=0.8)
    row = healer.cooldowns_html([cd])
    assert "80% of the presses on another player" in row and "mostly cast on another player" in row


def test_a_ramp_answers_the_hit_after_it(monkeypatch):
    # Vashnik heroic, Discipline Priest: Evangelism at 0:24, 1:42 and 3:15 for the 0:40, 2:10 and 3:35 hits
    monkeypatch.setattr(healer, "_ramp_kind", lambda sid: True)  # a ramp's button by the game data
    ab = SimpleNamespace(id=1, name="Evangelism", users=1.0, per_kill=3.0)
    players = [{"casts": {1: [24.0, 102.0, 195.0]}} for _ in range(10)]
    tl = SimpleNamespace(abilities=[ab], duration=270.0, players=players)
    found = [healer.Moment(t, 1000.0, 5.0, "Caustic Surge") for t in (40.0, 130.0, 215.0)]
    cd = healer.cooldowns(tl, found, {1: (90.0, 1)})[0]
    assert cd.ramp and cd.near == ["0:40 Caustic Surge", "", ""]  # the next two come back from cooldown
    h = healer.HealerPrep("Boss", "heroic", "Discipline Priest", 10, 270.0, [100.0] * 54, found, [cd], [], [], [],
                          [])
    sheet = healer.render_sheet(h)
    assert "100% press Evangelism (about 0:24, a ramp ahead of it)" in sheet
    assert "pressed again as soon as it is back" not in sheet  # its rhythm line says it (round 30)
    assert "0:24 &middot; 16 s before the 0:40 hit" in sheet
    assert "1:42 &middot; 28 s before the 2:10 hit &middot; 100%&nbsp;&middot;&nbsp;&#10226;</span>" in sheet


def test_back_from_cooldown_is_read_per_player():
    # Vashnik heroic, Disc: some press Evangelism at 0:04 then 1:42 (98 s, its cooldown 90): back as soon as it can
    # be, although the 0:04 and 2:07 moments are 123 s apart; others hold their first to 0:24
    per_player = [[4.0, 102.0, 195.0]] * 6 + [[24.0, 127.0]] * 4
    assert healer.back_share(per_player, 102.0, 90.0) == 1.0
    assert healer.back_share(per_player, 127.0, 90.0) == 0.0  # 103 s after 0:24: held
    assert healer.back_share(per_player, 24.0, 90.0) == 0.0  # a first press


def test_the_talents_they_differ_on_most_when_none_splits_them():
    # Holy Paladin: no talent taken by 35-65% of them, so the change tab names the ones they differ on most
    page = healer.split_html([("Tower of Radiance", 0.22)], 100, "Holy Paladin", wide=True)
    assert "differ on most</h2>" in page and "No talent splits them near half; these are the ones 15 to 85%" in page


def test_jobs_lead_says_either_only_when_your_spec_has_no_job():
    from types import SimpleNamespace as N
    mine = N(spec="Holy Priest", jobs=["dispels more: 1.4 times a minute"])
    other = N(spec="Restoration Shaman", jobs=["nothing stands out against the other healers"])
    assert "No other healer spec stands out." in healer.jobs_lead([mine, other], "Holy Priest")
    assert "either" not in healer.jobs_lead([mine, other], "Holy Priest")
    assert "stands out either" in healer.jobs_lead([other], "Restoration Shaman")


def test_two_rhythms_are_said_apart():
    # Disc, Vashnik heroic (round 32): 32 players press Evangelism at 0:04, 1:42, 3:15, 38 at 0:23, 2:01, 3:35, their
    # second press spread from 1:46 to 2:18
    per_player = ([[4.0, 99.0 + k % 3 * 3, 195.0] for k in range(32)]
                  + [[23.0, 106.0 + k % 5 * 7, 215.0] for k in range(38)] + [[60.0]] * 30)
    got = healer.rhythms(per_player, [4.0, 127.0, 218.0], [24.0, 102.0, 195.0], 100)
    assert [(sp, [round(t) for t in ts]) for sp, ts in got] == [(0.32, [4, 102, 195]), (0.38, [23, 120, 215])]
    assert healer.rhythms(per_player[:40], [4.0, 127.0, 218.0], [24.0, 102.0, 195.0], 100) == []  # 8 of 100: no


def test_a_button_with_two_rhythms_takes_their_moments():
    # the chips read 0:03, 2:11, 3:39: one group's opener with the other's later presses (round 32)
    ab = SimpleNamespace(id=1, name="Evangelism", users=0.7, per_kill=3.0)
    per_player = ([[4.0, 102.0, 195.0]] * 32 + [[23.0, 121.0, 215.0]] * 38 + [[]] * 30)
    tl = SimpleNamespace(abilities=[ab], duration=270.0, players=[{"casts": {1: ts}} for ts in per_player])
    c = healer.cooldowns(tl, [], {1: (90.0, 1)})[0]
    assert [round(t) for t in c.times] == [23, 121, 215] and [round(t) for t in c.alt] == [4, 102, 195]
    assert [round(t) for t in c.alt_of] == [23, 121, 215] and len(c.rhythms) == 2


def test_a_ramp_of_one_rhythm_says_the_other(monkeypatch):
    # Disc, Vashnik (round 33): a third ramps at 0:23 and 2:05 for the 0:40 and 2:10 hits, a third from the pull
    monkeypatch.setattr(healer, "_ramp_kind", lambda _sid: True)
    ab = SimpleNamespace(id=1, name="Evangelism", users=0.7, per_kill=3.0)
    per_player = ([[4.0, 102.0, 195.0]] * 32 + [[23.0, 125.0, 218.0]] * 38 + [[]] * 30)
    tl = SimpleNamespace(abilities=[ab], duration=270.0, players=[{"casts": {1: ts}} for ts in per_player])
    found = [healer.Moment(40.0, 1000.0, 5.0, "Caustic Surge"), healer.Moment(140.0, 1000.0, 5.0, "Caustic Surge")]
    cd = healer.cooldowns(tl, found, {1: (90.0, 1)})[0]
    h = healer.HealerPrep("Boss", "heroic", "Discipline Priest", 100, 270.0, [100.0] * 54, found, [cd], [], [], [], [])
    sheet = healer.render_sheet(h)
    assert "Evangelism is their ramp ahead of the 0:40 and 2:20 hits" in sheet
    assert "another 32% press it from the pull on its cooldown, about 0:04, 1:42 and 3:15" in sheet


def test_a_tied_press_is_counted_in_its_hits_window():
    # Mistweaver, Vashnik (round 34): Revival "49% about 0:45" counted presses up to 0:53, 13 s after the 0:40 hit
    c = healer.Cooldown("Revival", 1, 0.9, 1.0, [45.0], presses=[[42.0]] * 35 + [[52.0]] * 14 + [[100.0]] * 41,
                        n_all=100)
    assert healer.hit_share(c, 45.0, 40.0) == 0.35
    c.ramp = True  # a ramp 17 s ahead: its own time's window
    assert healer.hit_share(c, 23.0, 40.0) == 0.0


def test_a_hit_kept_for_none_names_a_few_presses_in_it():
    # Disc, Nek'zali (round 36): 20% of the top Discs press Ultimate Penitence in the 0:35 hit, under the quarter bar
    m = healer.Moment(35.0, 1000.0, 1.6, "Soulcoil Rite")
    up = healer.Cooldown("Ultimate Penitence", 1, 0.6, 1.0, [75.0], ["1:15 Soulcoil Rite"],  # it answers 1:15
                         presses=[[36.0]] * 20 + [[75.0]] * 40, n_all=100)
    ns = healer.Cooldown("Nature's Swiftness", 2, 0.9, 4.0, [35.0], every=60.0,
                         presses=[[36.0]] * 15 + [[90.0]] * 75, n_all=100)
    assert healer.landed_in(m, [up, ns]) == " (only 20% press Ultimate Penitence in its window, about 0:36)"
    up.presses = [[36.0]] * 30 + [[75.0]] * 30  # a quarter or more, no chip near: named, no "only" (round 101:
    got = healer.landed_in(m, [up, ns])  # not none, said why (rounds 102, 103)
    assert got == " (30% press Ultimate Penitence in its window, about 0:36)"  # its 0:36 shared by half: no false why



def test_a_minute_button_in_a_bare_hit_is_named_with_its_reason():
    # Restoration Druid, Nek'zali (round 37): 70% press Convoke 4 s before the 1:15 hit, the lead said nothing
    m = healer.Moment(75.0, 1000.0, 1.6, "Soulcoil Rite")
    cv = healer.Cooldown("Convoke the Spirits", 1, 1.0, 4.0, [6.0, 71.0], support=[0.76, 0.7], why="about every minute")
    assert healer.landed_in(m, [cv]) == (" (70% press Convoke the Spirits in its window, about 1:11, pressed about "
                                         "every minute)")
    inn = healer.Cooldown("Innervate", 2, 1.0, 2.0, [49.0], presses=[[75.0]] * 11 + [[49.0]] * 89, n_all=100)
    assert healer.landed_in(m, [inn]) == " (no raid cooldown of theirs pressed by a tenth of them in it)"


def test_the_other_healers_are_read_over_the_hits_window():
    # Preservation Evoker, Nek'zali (round 40): Rewind in the 1:15 window (1:10-1:23) for 26%, 20% around its peak
    ps = [[71.0]] * 20 + [[82.0]] * 6 + [[37.0]] * 30 + [[200.0]] * 24
    got = healer._in_hit("Rewind", [], [0.8, (ps, 100, 240.0)], 75.0)
    assert got[0] == "Rewind" and got[2] == 0.26
    back = [[10.0, 75.0]] * 30 + [[200.0]] * 50  # every press back from a 60 s cooldown: no answer
    assert healer._in_hit("X", [], [0.8, (back, 100, 60.0)], 75.0) is None


def test_no_job_kept_by_the_top_players_is_the_answer():
    # Nek'zali (round 41): every job found is taken back on the ranked players
    hp = SimpleNamespace(spec="Holy Paladin", jobs=[
        "heals the tanks more, but only on average: 9% of its healing goes on them, against 7% for the other healers "
        "of the same kills (548 kills); among the top players ranked by their healing there is no gap: the median "
        "top Holy Paladin 8%, the other specs' 8% (40 and 300 ranked players, one in each top kill of each healer "
        "spec's sheet)"])
    sh = SimpleNamespace(spec="Restoration Shaman", jobs=["nothing stands out against the other healers"])
    lead = healer.jobs_lead([hp, sh], "Restoration Shaman")
    assert lead.startswith("<p class='lead'>No healer spec has a job of its own here that the top players keep.</p>")
    assert ("Holy Paladin</b></td><td>heals the tanks more</td><td><b>9%</b> vs 7% <small>(548 kills)"
            "</small></td><td><b>8%</b> vs 8%</td>") in lead  # a table: every healer, then the top players
    hp.tank = 0.08  # the table's own number beside the means (round 78)
    assert "(548 kills; the table&#x27;s median Holy Paladin: 8%)</small>" in healer.jobs_lead([hp, sh],
                                                                                              "Restoration Shaman")


def test_a_press_is_said_at_its_most_shared_time():
    # Restoration Druid, Nek'zali (round 41): Convoke's third press "2:24 · 27%, or 2:37 for 28%"
    ab = SimpleNamespace(id=1, name="Convoke the Spirits", users=1.0, per_kill=1.0)
    per_player = [[144.0]] * 27 + [[157.0]] * 28 + [[]] * 45
    tl = SimpleNamespace(abilities=[ab], duration=270.0, players=[{"casts": {1: ts}} for ts in per_player])
    c = healer.cooldowns(tl, [], {1: (120.0, 1)})[0]
    assert c.times == [157.0] and c.alt == [144.0]


def test_the_other_healers_read_a_ramp_ahead_of_the_hit(monkeypatch):
    # Discipline Priest, Vashnik (round 44): Evangelism 8-30 s before 0:40 for a quarter, "none shared" in the window
    monkeypatch.setattr(healer, "_ramp_kind", lambda sid: sid == 472433)
    ps = [[19.0]] * 30 + [[40.0]] * 10 + [[200.0]] * 60
    got = healer._in_hit("Evangelism", [], [1.0, (ps, 100, 90.0, 472433)], 40.0)
    assert got[1] == 19.0 and got[2] == 0.3 and got[4] is True


def test_the_pull_opener_is_no_ramp_for_the_first_hit(monkeypatch):
    # Discipline Priest, Nek'zali (round 45): Evangelism 0:00-0:09 read "0:08 (a ramp)" for the 0:35 hit
    monkeypatch.setattr(healer, "_ramp_kind", lambda sid: True)
    ps = [[float(k % 10)] for k in range(60)] + [[200.0]] * 40
    assert healer._in_hit("Evangelism", [], [1.0, (ps, 100, 90.0, 1)], 35.0, bar=False) is None


def test_a_late_hits_share_is_of_the_kills_that_reach_it():
    # Protection Warrior, Nek'zali (round 47): 42 of the 100 top kills end before the 3:55 hit
    c = healer.Cooldown("Shield Wall", 1, 0.9, 2.0, [231.0], presses=[[231.0]] * 19 + [[34.0]] * 70, n_all=100,
                        lasts=[300.0] * 58 + [200.0] * 42)
    assert round(healer.hit_share(c, 231.0, 235.0), 2) == 0.33
    assert healer._reach_note(c, 235.0) == " (58 kills going)"


def test_a_late_tied_chip_says_its_base_and_a_named_time_is_its_presses():
    # Protection Warrior, Nek'zali (round 53): "33%" for 19 of the 58 kills still going
    c = healer.Cooldown("Shield Wall", 1, 0.9, 2.0, [231.0], presses=[[234.0]] * 19 + [[34.0]] * 70, n_all=100,
                        lasts=[300.0] * 58 + [200.0] * 42)
    assert healer._base(c, 19 / 58, 235.0) == " &middot; 33% (58 kills going)"
    m = healer.Moment(235.0, 1000.0, 1.5, "Hollowing Strikes")
    c.why, c.back, c.support = "", [231.0], [0.24]
    assert "about 3:54" in healer.landed_in(m, [c])  # the presses counted (3:54), not the moment (3:51)


def test_a_button_on_cooldown_keeps_a_held_habit_for_a_hit():
    # Holy Paladin, Nek'zali (round 74): 26% hold their first Avenging Wrath for the 0:35 hit, the rest press it from
    # the pull on its 120 s cooldown; the held group was dropped with the button's "on cooldown" label
    ab = SimpleNamespace(id=1, name="Avenging Wrath", users=1.0, per_kill=2.0)
    per_player = [[4.0, 126.0]] * 60 + [[35.0, 180.0]] * 30 + [[]] * 10
    tl = SimpleNamespace(abilities=[ab], duration=270.0, players=[{"casts": {1: ts}} for ts in per_player])
    found = [healer.Moment(35.0, 1000.0, 1.6, "Soulcoil Rite")]
    c = healer.cooldowns(tl, found, {1: (120.0, 1)})[0]
    assert 35.0 in [round(a) for a in c.alt] and any(n.startswith("0:35") for n in c.alt_near)


def test_a_minute_buttons_far_habit_is_a_moment_of_its_own():
    # Restoration Druid, Vashnik (round 76): Nature's Swiftness "2:09 · 28% …, or 1:22 for 27%", 47 s apart
    ab = SimpleNamespace(id=1, name="Nature's Swiftness", users=1.0, per_kill=4.0)
    per_player = [[10.0, 70.0, 129.0, 190.0]] * 50 + [[10.0, 82.0, 160.0, 230.0]] * 45 + [[]] * 5
    tl = SimpleNamespace(abilities=[ab], duration=270.0, players=[{"casts": {1: ts}} for ts in per_player])
    c = healer.cooldowns(tl, [], {1: (60.0, 1)}, min_users=0.0)[0]
    assert c.why == healer.MINUTE and {160.0, 230.0} <= set(c.times)
    assert all(abs(a - o) <= healer.OR_NEAR for a, o in zip(c.alt, c.alt_of, strict=False))


def test_the_other_healers_chip_gives_the_share_the_bar_reads():
    # Nek'zali (round 76): Tranquility "1:14 · 24%" passed the quarter bar on those who press it, unsaid
    rd = SimpleNamespace(spec="Restoration Druid", raid_cds=1, own_players=150,
                         cd_names=[("Tranquility", 1, [], 0.8, ([[74.0]] * 24 + [[200.0]] * 56, 100, 180.0))])
    out = healer.roles_more([rd], found=[healer.Moment(75.0, 1000.0, 1.6, "Soulcoil Rite")])
    assert "<b>Tranquility</b> 1:14 &middot; 24% <small>(30% of its users)</small>" in out


def test_a_button_on_cooldowns_far_habit_is_dropped():
    # Mistweaver Monk, Nek'zali (round 77): Celestial Conduit "on cooldown, about every 97 s" showed 3:20 and 3:46
    ab = SimpleNamespace(id=1, name="Celestial Conduit", users=1.0, per_kill=3.0)
    per_player = [[5.0, 100.0, 195.0]] * 55 + [[5.0, 100.0, 230.0]] * 45
    tl = SimpleNamespace(abilities=[ab], duration=270.0, players=[{"casts": {1: ts}} for ts in per_player])
    c = healer.cooldowns(tl, [], {1: (90.0, 1)})[0]
    assert c.every and 230.0 not in c.times and 230.0 not in c.alt


def test_a_chip_says_back_from_cooldown_once():
    # Protection Warrior, Nek'zali (round 78): Shield Wall "3:51 · 24% · back from cooldown for about half · in the
    # window of the 3:55 hit: 28% …, back from cooldown for about half"
    c = healer.Cooldown("Shield Wall", 1, 0.9, 2.0, [231.0], [""], cd=180.0,
                        presses=[[50.0, 234.0]] * 10 + [[234.0]] * 9 + [[34.0]] * 70, n_all=100,
                        lasts=[300.0] * 58 + [200.0] * 42, back=[231.0], back_half=[231.0], support=[0.24])
    out = healer.cooldowns_html([c], set(), {("Shield Wall", 231.0): 235.0})
    assert out.count("&#10226;") == 1, out  # the glyph the legend defines


def test_a_cadence_names_its_group_beside_a_held_habit():
    # Holy Paladin, Nek'zali (round 79): "on cooldown, about every 122 s" beside 26% holding Avenging Wrath for 0:35
    c = healer.Cooldown("Avenging Wrath", 1, 1.0, 3.0, [4.0, 125.0, 248.0], ["", "", ""], alt=[35.0],
                        every=122.0, alt_support=[0.29], alt_near=["0:35 Soulcoil Rite"], alt_of=[4.0])
    out = healer.cooldowns_html([c], {("Avenging Wrath", 35.0)})
    assert ("on cooldown from 0:04, about every 122 s; those pressing it at 0:35 instead press it again at varying "
            "times" in out)
    c.alt_near = [""]
    assert "on cooldown, about every 122 s<" in healer.cooldowns_html([c])


def test_a_two_step_button_says_its_release_and_what_it_stores():
    # Preservation Evoker, Vashnik (round 79, the owner): Stasis stored at 3:20, released at 3:36 in the 3:35 window
    import sqlite3

    from paf.corpus.db import SCHEMA

    store = SimpleNamespace(id=1, name="Stasis (Store)", users=1.0, per_kill=1.0)
    rel = SimpleNamespace(id=2, name="Stasis (Release)", users=0.9, per_kill=1.0)
    players = ([{"casts": {1: [200.0], 2: [216.0]}, "duration": 270.0}] * 50
               + [{"casts": {1: [100.0], 2: [116.0]}, "duration": 270.0}] * 50)
    tl = SimpleNamespace(abilities=[store, rel], duration=270.0, players=players)
    c = healer.Cooldown("Stasis (Store)", 1, 1.0, 1.0, [200.0], [""], presses=[[200.0]] * 50, n_all=100)
    m = healer.Moment(215.0, 1000.0, 1.4, "Caustic Surge")
    healer.two_step(tl, [c], [m])
    assert c.release_gap == 16.0 and round(healer.hit_share(c.release, 215.0, 215.0), 2) == 0.5
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO ability VALUES(?, ?)", [(1, "Stasis (Store)"), (2, "Stasis (Release)"),
                                                          (3, "Dream Breath"), (4, "Temporal Anomaly"), (5, "Hover")])
    for k in range(4):
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 4, 270, 'done')", (f"r{k}",))
        con.execute("INSERT INTO ranked(report, fight_id, actor_id, rank_pos) VALUES(?, 1, 5, 1)", (f"r{k}",))
        for t, ab in [(10, 1), (11, 3), (12, 3 if k else 5), (13, 4), (14, 2)]:
            con.execute("INSERT INTO player_cast(report, fight_id, actor_id, ability_id, type, t) "
                        "VALUES(?, 1, 5, ?, 'cast', ?)", (f"r{k}", ab, float(t)))
    assert healer.stored_spells(con, 9, 4, "Stasis (Store)") == [("Dream Breath", 1.0, 0.75),
                                                                   ("Temporal Anomaly", 1.0, 0.0),
                                                                   ("Hover", 0.25, 0.0)]
    c.stored = healer.stored_spells(con, 9, 4, "Stasis (Store)")
    out = healer.cooldowns_html([c])
    assert ("released:</small><span class='chip'>3:36 &middot; 50% &middot; from the 3:20 store, "
            "each a median 16 s after its own (nearly all released)</span>") in out  # the any-store chip says the hit
    assert "and about 0.5 more releases a kill, of stores made at other times" in out  # the 1:40 stores
    assert "any store &rarr; 3:35 hit &middot; 50% &middot; held 16 s</span>" in out
    # a store never released before the next store is not paired with the next one's release (round 83)
    tl.players = [{"casts": {1: [100.0, 200.0], 2: [216.0]}, "duration": 270.0}] * 4
    healer.two_step(tl, [c], [m])
    assert c.release_gap == 16.0 and c.unreleased == 0.5
    assert "<span class='chip'>Dream Breath &middot; 100% &middot; twice 75%</span>" in out


def test_two_groups_of_presses_in_a_window_are_said_apart():
    # Discipline Priest, Vashnik (round 77): Evangelism ahead of 2:10 at 1:41 and 2:01, "about 1:48" nobody presses
    assert healer._about([101.0] * 20 + [121.0] * 21) == "1:41 or 2:01"
    assert healer._about([101.0, 103.0, 104.0, 106.0, 108.0]) == "1:44"
    spread = [100.0, 101, 101, 104, 105, 105, 108, 108, 109, 114, 115, 118, 119, 120, 121, 121]  # the real 1:40-2:01
    assert healer._about(spread) == "1:44 to 1:59"
    assert healer._center([101.0] * 20 + [121.0] * 21) == 121.0
    assert healer._about([70.0] * 3 + [72.0] * 13 + [74.0] * 10 + [80.0] * 11 + [82.0] * 10) == "1:12 or 1:20"  # r105


def test_a_named_chip_with_one_share_shows_one_time():
    # Protection Warrior, Vashnik (round 78): Shield Wall "2:59 · 15% … in the window of the 2:55 hit, about 2:57"
    c = healer.Cooldown("Shield Wall", 1, 0.6, 2.0, [179.0], [""], support=[0.15],
                        presses=[[177.0]] * 15 + [[60.0]] * 45, n_all=100)
    out = healer.cooldowns_html([c], set(), {("Shield Wall", 179.0): 175.0})
    assert ("2:57 &middot; 2 s after the 2:55 hit starts &middot; 15% (25% of its users)</span>"
            in out and "about" not in out and "the same" not in out)


def test_a_share_under_a_quarter_gives_the_pressers_share():
    # Protection Warrior, Vashnik (round 83): "Shield Wall 2:57 · 15%" read as under the quarter rule
    c = healer.Cooldown("Shield Wall", 1, 0.6, 2.0, [177.0], [""], support=[0.15])
    assert healer._pressers(c, 0.15) == " (25% of its users)"
    assert healer._pressers(c, 0.3) == ""
    c.release_pairs = [(216.0, 13.0), (217.0, 12.0), (130.0, 30.0)]  # a hit's releases: their own stores' gap
    assert healer._gap_of(c, [216.0, 217.0]) == 12.5


def test_a_ramp_on_the_other_healers_lines_is_one_its_players_play(monkeypatch):
    # Vashnik (round 85): Tip the Scales "3:14 (a ramp)" for the 3:35 hit, a spell mod no Evoker plays as a ramp
    monkeypatch.setattr(healer, "_ramp_kind", lambda sid: True)
    ps = [[194.0]] * 15 + [[60.0]] * 70 + [[]] * 15
    ev = SimpleNamespace(spec="Preservation Evoker", raid_cds=1, own_players=150,
                         cd_names=[("Tip the Scales", 1, [], 0.85, (ps, 100, 120.0, 370553))])
    found = [healer.Moment(t, 1000.0, 1.4, "Caustic Surge") for t in (40.0, 130.0, 215.0)]
    assert "(a ramp)" not in healer.roles_more([ev], found=found)


def test_a_ramp_played_back_from_cooldown_stays_a_ramp(monkeypatch):
    # Discipline Priest, Vashnik (round 86): Evangelism ahead of 2:10 and 3:35, the 3:35 one back from cooldown, lost
    # its ramp when the check dropped presses back from cooldown
    monkeypatch.setattr(healer, "_ramp_kind", lambda sid: True)
    ps = [[109.0, 194.0]] * 40 + [[60.0]] * 60
    di = SimpleNamespace(spec="Discipline Priest", raid_cds=1, own_players=100,
                         cd_names=[("Evangelism", 1, [], 1.0, (ps, 100, 90.0, 472433))])
    found = [healer.Moment(t, 1000.0, 1.4, "Caustic Surge") for t in (40.0, 130.0, 215.0)]
    assert "<b>Evangelism</b> 1:49 <small>(a ramp)</small>" in healer.roles_more([di], found=found)


def test_a_chip_offset_is_the_shown_times_difference():
    # round 87: "0:40 · 1 s before the 0:40 hit" (39.6 s shown rounded, the gap from the truncated 39)
    assert healer._chip(39.6, "0:40 Caustic Surge") == "0:40 &middot; on the hit"
    assert healer._chip(33.5, "0:35 Soulcoil Rite") == "0:34 &middot; 1 s before the 0:35 hit"


def test_a_once_a_kill_button_says_the_rest_of_its_presses():
    # Discipline Priest, Nek'zali (round 87): Ultimate Penitence pressed by 97%, chips at 27% and 20%
    c = healer.Cooldown("Ultimate Penitence", 1, 0.97, 1.0, [75.0], ["1:15 Soulcoil Rite"], alt=[36.0],
                        support=[0.27], alt_support=[0.2], alt_of=[75.0])
    assert "the other 50% at varying times" in healer.cooldowns_html([c])


def test_the_rest_leaves_out_a_named_line_and_a_tied_chip_gives_its_pressers():
    # Discipline Priest, Nek'zali (round 89): "the other 69%" counted the 20% named in the 0:35 window again
    c = healer.Cooldown("Ultimate Penitence", 1, 0.97, 1.0, [76.0], [""], support=[0.27])
    named = {("Ultimate Penitence", ("line", 35.0)): (0.2, "0:37", "", "")}
    assert round(healer._rest(c, named), 2) == 0.5
    # Protection Warrior, Nek'zali: "0:34 · 1 s before the 0:35 hit · 23%" without the pressers' share
    sw = healer.Cooldown("Shield Wall", 1, 0.77, 2.0, [34.0], ["0:35 Soulcoil Rite"], support=[0.23],
                         presses=[[34.0]] * 23 + [[100.0]] * 54, n_all=100)
    assert healer._also_pressers(sw, 34.0, {}, "0:35 Soulcoil Rite", 0.23) == " (30% of its users)"


def test_a_named_chip_with_two_shares_gives_its_pressers():
    # Protection Warrior, Nek'zali (round 90): "3:52 · 24% · in the window of the 3:55 hit: 28%" without its 31%
    c = healer.Cooldown("Shield Wall", 1, 0.77, 2.0, [232.0], [""], support=[0.24],
                        presses=[[234.0]] * 16 + [[232.0]] * 8 + [[100.0]] * 53, n_all=100,
                        lasts=[300.0] * 58 + [200.0] * 42)
    assert healer._also_pressers(c, 232.0, {("Shield Wall", 232.0): 235.0}, "", 0.24) == " (31% of its users)"


def test_an_untied_time_in_a_hit_window_says_it_is_not_kept():
    # Mistweaver Monk, Nek'zali (round 90): Invoke Yu'lon "or 0:32 for 30%" in the 0:35 hit's window, no reason
    c = healer.Cooldown("Invoke Yu'lon", 1, 1.0, 2.0, [5.0], [""], alt=[32.0], alt_support=[0.3], alt_of=[5.0],
                        alt_near=["0:35 Soulcoil Rite"], presses=[[32.0]] * 16 + [[5.0]] * 84, n_all=100)
    assert "or 0:32 &middot; not kept for the 0:35 hit: 16% in its window" in healer.cooldowns_html([c], set())


def test_a_held_habit_of_a_button_on_cooldown_says_it_is_not_kept():
    # Mistweaver Monk, Nek'zali (round 91): Celestial Conduit "0:05 · 58%, or 0:37 for 25%" in the 0:35 hit, no clause
    c = healer.Cooldown("Celestial Conduit", 1, 1.0, 3.0, [5.0], [""], alt=[37.0], alt_support=[0.25],
                        alt_of=[5.0], alt_near=["0:35 Soulcoil Rite"], every=97.0,
                        presses=[[37.0]] * 25 + [[5.0]] * 75, n_all=100)
    assert "or 0:37 &middot; not kept for the 0:35 hit: 25% in its window" in healer.cooldowns_html([c], set())


def test_a_first_press_at_the_pull_says_so_on_hover():
    # Holy Paladin, Nek'zali (round 92): "Avenging Wrath 0:04 (tied to no hit: on cooldown)"
    c = healer.Cooldown("Avenging Wrath", 1, 1.0, 3.0, [4.0, 126.0], ["", ""], every=122.0)
    assert healer._why_not(c, 4.0) == ": at the pull" and healer._why_not(c, 126.0) == ": on cooldown"


def test_every_outline_gives_its_reason():
    # round 93: Stasis 1:57 "on cooldown" for a group held past it; four outlines with no reason at all
    hit = healer.Moment(130.0, 1000.0, 1.4, "Caustic Surge")
    st_ = healer.Cooldown("Stasis (Store)", 1, 1.0, 3.0, [101.0], [""], alt=[117.0], every=99.0)
    st_.fates = [(117.0, 131.0)] * 9
    assert healer._why_not(st_, 117.0, [hit]) == ": its release goes on the 2:10 hit"
    sw = healer.Cooldown("Shield Wall", 2, 0.8, 2.0, [69.0, 231.0], ["", ""])
    assert healer._why_not(sw, 69.0, [hit]) == ": away from the big hits"
    assert healer._why_not(sw, 115.0, [hit]) == ": before the 2:10 hit's window"
    assert healer._why_not(sw, 128.0, [hit]) == ": in the 2:10 hit's window, not kept for it"


def test_an_on_cooldown_button_says_so_on_hover():
    # Holy Paladin, Nek'zali (round 94): Avenging Wrath 2:05, on cooldown, read "back from cooldown" on hover
    c = healer.Cooldown("Avenging Wrath", 1, 1.0, 3.0, [4.0, 125.0], ["", ""], every=122.0, back=[125.0])
    assert healer._why_not(c, 125.0, []) == ": on cooldown"


def test_a_talent_choice_side_keeps_its_note_muted():
    # Protection Warrior (round 94): "Sudden Death 38% (3% take" in bold, "neither)" muted
    assert (healer._side("Sudden Death 38% (3% take neither)")
            == "<b>Sudden Death</b> <small>38% (3% take neither)</small>")
    assert healer._side("Bloodborne 59%") == "<b>Bloodborne</b> <small>59%</small>"


def test_more_counts_a_press_named_in_a_hit_window():
    # Holy Priest, Vashnik (round 94): Apotheosis "2 a kill", a 0:40 chip, "about 2:16" and "+1 more"
    c = healer.Cooldown("Apotheosis", 1, 1.0, 2.0, [40.0], ["0:40 Caustic Surge"])
    assert healer._more(c) == "+1"
    assert healer._more(c, {("Apotheosis", ("line", 130.0)): (0.12, "2:16", "", "")}) == ""


def test_a_quarter_not_kept_names_the_button_kept():
    # Mistweaver Monk, Nek'zali (round 95): Conduit "not kept for the 0:35 hit: 25%" beside the note's quarter bar
    named = {(healer.KEPT, 35.0): ("Revival / Restoral", 0.38)}
    assert (healer._not_kept(35.0, 0.25, named)
            == " &middot; not kept for the 0:35 hit: 25% in its window, under Revival / Restoral's 38%"
            "")
    assert healer._not_kept(35.0, 0.16, named) == (" &middot; not kept for the 0:35 hit: 16% in its window, under "
                                                   "Revival / Restoral's 38%")  # round 105


def test_a_late_time_share_says_the_kills_still_going():
    # Protection Warrior, Nek'zali (round 98): "3:52 · 24%" of 100 beside "28% … in the 58 kills still going"
    c = healer.Cooldown("Shield Wall", 1, 0.77, 2.0, [232.0], [""], lasts=[300.0] * 58 + [200.0] * 42)
    assert healer._still(c, 232.0) == " (58 kills going)"
    assert healer._still(c, 100.0) == ""
    c.lasts = [300.0] * 99 + [200.0]  # one kill ended: the share reads the same over all, nothing said (round 99)
    assert healer._still(c, 232.0, 0.25) == "" and healer._still(c, 232.0) == " (99 kills going)"


def test_the_pull_group_a_card_shows_is_drawn():
    # Holy Priest, Nek'zali (round 99): Divine Hymn's 0:05 pull group on the card and in the lead, not on the chart
    c = healer.Cooldown("Divine Hymn", 1, 1.0, 2.0, [36.0], ["0:35 Soulcoil Rite"],
                        presses=[[5.0, 75.0]] * 23 + [[36.0, 75.0]] * 77, n_all=100)
    found = [healer.Moment(35.0, 1000.0, 1.6, "Soulcoil Rite")]
    svg = healer.curve_svg([100.0] * 60, found, [], "x", [c], {"Divine Hymn"}, {("Divine Hymn", 36.0)})
    assert "Divine Hymn 0:05 (tied to no hit: at the pull)" in svg


def test_back_from_cooldown_reads_its_gap_in_pull_time():
    # Preservation Evoker, Nek'zali (round 101): a Rewind gap read 178 s in stage time for 245 s in the kill
    stage = [[70.0, 248.0]]
    pull = [[70.0, 315.0]]
    assert healer.back_share(stage, 248.0, 180.0) == 1.0  # in stage time: back as soon as it came back
    assert healer.back_share(stage, 248.0, 180.0, pull) == 0.0  # in pull time: held 65 s past it


def test_a_hit_window_a_quarter_press_in_gets_a_time():
    # Restoration Druid, Nek'zali (round 106): Tranquility 26% in the 4:15 window, its presses spread 4:12-4:23, no
    # time of its card there: refused while Aura Mastery 23% was kept by its time
    ab = SimpleNamespace(id=1, name="Tranquility", users=1.0, per_kill=2.0)
    per_player = ([[36.0, 252.0 + k % 11] for k in range(26)] + [[36.0, 232.0]] * 36 + [[36.0, 300.0]] * 24
                  + [[36.0]] * 14)
    tl = SimpleNamespace(abilities=[ab], duration=320.0,
                         players=[{"casts": {1: ts}, "duration": 330.0} for ts in per_player])
    found = [healer.Moment(t, 1000.0, 1.5, "x") for t in (35.0, 230.0, 255.0)]
    c = healer.cooldowns(tl, found, {1: (180.0, 1)})[0]
    assert any(n.startswith("4:15") for n in [*c.near, *c.alt_near])  # a time tied to it, main or habit


def test_the_pressers_share_uses_the_keep_tests_base():
    # Holy Paladin, Nek'zali (round 108): "or 3:49 for 18% (24% of its users)" shown past the quarter bar
    c = healer.Cooldown("Divine Protection", 1, 0.74, 2.0, [229.0], [""], presses=[[229.0]] * 74,
                        press_lasts=[300.0] * 70 + [200.0] * 4, lasts=[300.0] * 90 + [200.0] * 10)
    assert healer._pressers(c, 0.18) == " (24% of its users)"  # over every kill
    assert healer._pressers(c, 0.18, 229.0) == " (23% of its users)"  # of the kills still going: 70 of 90


def test_the_other_share_counts_players_not_shares():
    # Protection Warrior, Nek'zali (round 109): 52% press Rallying Cry, its chip 15%, "the other 36%"
    c = healer.Cooldown("Rallying Cry", 1, 0.52, 1.0, [230.0], [""], support=[0.15], n_all=100,
                        presses=[[230.0]] * 15 + [[120.0]] * 37)
    assert round(healer._rest(c), 2) == 0.37


def test_a_button_pressed_twice_by_some_says_so():
    # Discipline Priest, Nek'zali (round 110): 27 + 20 + 15 + "the other 38%" past the 97% who press it
    c = healer.Cooldown("Ultimate Penitence", 1, 0.97, 1.0, [76.0, 230.0], ["", ""], support=[0.62, 0.31],
                        n_all=100, presses=[[76.0, 230.0]] * 31 + [[76.0]] * 31 + [[150.0]] * 35)
    assert healer._twice(c) == " (31% press it twice: a player can count in two shares)"


def test_twice_is_said_only_when_the_shares_add_past_the_pressers():
    # Restoration Shaman, Vashnik (heal round 10): Spirit Link Totem 17% at 2:10 + "the other 76%" = its 93%
    c = healer.Cooldown("Spirit Link Totem", 1, 0.93, 1.0, [130.0], [""], support=[0.17], n_all=100,
                        presses=[[130.0, 250.0]] * 17 + [[50.0]] * 76)
    assert healer._twice(c) == ""


def test_a_side_line_gives_each_time_its_share():
    # Holy Paladin, Nek'zali (round 111): "Divine Steed (71%, about 2:20)" read as 71% at 2:20, 29% press it there
    c = healer.Cooldown("Divine Steed", 1, 0.71, 2.0, [140.0], [""], support=[0.29])
    assert healer._times_line(c) == "pressed by 71%; 29% about 2:20"


def test_split_list_names_a_tie_at_its_cut():
    # round 114: Oppressing Roar at 30% left out beside Scarlet Adaptation at 30%, the fourth named
    split = [("Stretch Time", 0.48), ("Extended Flight", 0.56), ("Foci of Life", 0.36),
             ("Scarlet Adaptation", 0.30), ("Oppressing Roar", 0.30), ("Hover", 0.2)]
    text = healer._many(split)
    assert "Oppressing Roar" in text and "Hover" not in text


def test_hit_dot_has_a_hover():
    found = [healer.Moment(230.0, 300.0, 1.41, "Possession Barrage")]
    svg = healer.curve_svg([100.0] * 300, found, [("Stage Two", 178.0)], "x")
    assert "<title>3:50 &middot; mostly Possession Barrage &middot; 1.41&times; the usual damage &middot; " \
           "Stage Two +0:52</title>" in svg


def test_one_none_kept_reason_on_several_rows_is_said_once():
    # Protection Warrior, Vashnik (heal round 10): "None kept (no long defensive of theirs pressed by a tenth of
    # them in it)" on two rows under a lead saying none is kept
    found = [healer.Moment(t, 1000.0, 5.0, "Crush") for t in (60.0, 120.0, 175.0)]
    why = " (no long defensive of theirs pressed by a tenth of them in it)"
    late = why[:-1] + " (89 kills going))"  # Holy Paladin, Vashnik (heal rounds 11, 13): the count kept it apart
    out = healer.hits_table(found, found, [], {"1:00": why, "2:00": late, "2:55": " (12% press Shield Wall)"},
                            None, {}, "")
    assert out.count("pressed by a tenth") == 1
    assert "None kept with no reason beside it: no long defensive of theirs" in out
    assert "<span class='none'>None kept</span> (12% press Shield Wall)" in out


def test_a_release_kept_for_two_hits_is_named_once_in_the_lead():
    # Preservation Evoker, Vashnik (round 11): Stasis released in the 2:10 and 3:35 windows crashed the sheet
    # (a Cooldown deduplicated as a dict key)
    found = [healer.Moment(130.0, 1000.0, 1.6, "Caustic Surge"), healer.Moment(215.0, 1000.0, 1.6, "Caustic Surge")]
    rel = healer.Cooldown("Stasis (Release)", 2, 0.9, 2.0, [131.0, 216.0], ["", ""],
                          presses=[[131.0, 216.0]] * 9, n_all=10)
    st_ = healer.Cooldown("Stasis (Store)", 1, 1.0, 2.0, [100.0, 190.0], ["", ""],
                          presses=[[100.0, 190.0]] * 10, n_all=10, release=rel)
    h = healer.HealerPrep("Boss", "heroic", "Preservation Evoker", 10, 270.0, [100.0] * 54, found, [st_], [], [],
                          [], [])
    sheet = healer.render_sheet(h)
    assert sheet.count("release</b>") == 1


def test_a_choice_node_is_one_row_with_one_stacked_bar():
    # Protection Warrior (heal round 11): "Bloodborne 48% / Sudden Death 43% (9% take neither)" drawn with no bar
    row = healer.split_html([("Bloodborne 48% / Sudden Death 43% (9% take neither)", -1.0)], 100, "Protection Warrior")
    assert "<li class='pair'>" in row and "width:48%" in row and "width:43%" in row and "9% neither" in row


def test_a_press_in_a_hit_window_shows_one_share():
    # Holy Paladin, Nek'zali (heal round 11): "4:16 · 19% (26% of its users) · not kept for the 4:15 hit: 20% in its
    # window": three numbers for one press
    c = healer.Cooldown("Divine Protection", 1, 0.73, 1.0, [256.0], ["4:15 Hit"], support=[0.19], n_all=100,
                        presses=[[256.0]] * 20 + [[100.0]] * 53)
    out = healer.cooldowns_html([c], set())
    assert "4:16 &middot; not kept for the 4:15 hit: 20% in its window" in out and "19%" not in out


def test_a_chip_named_for_a_hit_window_shows_the_windows_share_only():
    # Holy Paladin, Nek'zali (heal round 12): "3:49 · 30% · in the window of the 3:50 hit: 22%"
    c = healer.Cooldown("Avenging Wrath", 1, 1.0, 3.0, [229.0], [""], support=[0.30], n_all=100,
                        presses=[[229.0]] * 22 + [[222.0]] * 8 + [[100.0]] * 70)
    out = healer.cooldowns_html([c], set(), {("Avenging Wrath", 229.0): 230.0})
    assert "in the window of the 3:50 hit: 22%" in out and "30%" not in out


def test_an_or_time_named_for_a_hit_shows_one_time_and_one_share():
    # Mistweaver, Vashnik (heal round 12): "or 2:10 for 32% · in the window of the 2:10 hit: 25%, about 2:11"
    c = healer.Cooldown("Celestial Conduit", 1, 1.0, 2.0, [111.0], [""], support=[0.40], alt=[130.0],
                        alt_support=[0.32], alt_of=[111.0], n_all=100,
                        presses=[[111.0]] * 40 + [[131.0]] * 25 + [[124.0]] * 7 + [[60.0]] * 28)
    out = healer.cooldowns_html([c], set(), {("Celestial Conduit", 130.0): 130.0})
    assert "or 2:11 &middot; in the window of the 2:10 hit: 25%</span>" in out and "32%" not in out


def test_a_main_time_with_its_reason_then_its_or():
    # Preservation Evoker, Nek'zali (heal round 12): "4:17, or 3:49 for 17% … · 4:17 not kept for the 4:15 hit"
    c = healer.Cooldown("Obsidian Scales", 1, 0.9, 2.0, [257.0], ["4:15 Hit"], support=[0.19], alt=[229.0],
                        alt_support=[0.17], alt_of=[257.0], n_all=100,
                        presses=[[257.0]] * 22 + [[229.0]] * 17 + [[100.0]] * 51)
    out = healer.cooldowns_html([c], set())
    assert "4:17 &middot; not kept for the 4:15 hit: 22% in its window, or 3:49 &middot; 17%" in out


def test_trinkets_and_split_talents_show_their_icons():
    # heal rounds 12-15: the Change tab had no icon at all
    out = healer.trinkets_html([("Soulcoiler Ritual Vessel", 1, 0.8)], {"Soulcoiler Ritual Vessel": "inv_x"})
    assert "inv_x" in out and "<small>80%</small>" in out
    assert "questionmark" not in healer.trinkets_html([("X", 1, 0.5)], {"X": "inv_misc_questionmark"})
    split = healer.split_html([("Lightburst", 0.48), ("Bloodborne 48% / Sudden Death 43%", -1.0)], 100, "X",
                              icons={"Lightburst": "spell_a", "Sudden Death": "spell_b"})
    assert "spell_a" in split and "spell_b" in split
