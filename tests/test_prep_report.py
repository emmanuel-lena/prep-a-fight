from paf.prep_report import PrepData, headline, render


def test_headline_speaks_the_players_language():
    from paf.fight import AddWave, Fight, Vulnerable
    from paf.optimize import Plan, Rule

    d = PrepData("Ula'tek", "heroic", "Elemental", "Char")
    d.fight = Fight("U", 600, add_waves=[AddWave(60, 5, 20)],
                    vulnerable=[Vulnerable(120, 40, 2.0, "Venomous Heart (after Mother's Wrath)")])
    d.cd_names = {"use_item:trinket1": "Vile Vial", "ascendance": "Ascendance"}

    def rule(name):
        return Rule(name, "", lambda old: old)

    p = Plan("boss", {"ascendance": rule("hold_vulnerable_60"), "use_item:trinket1": rule("hold_vulnerable_60"),
                      "stormkeeper": rule("add_waves")}, 10.3, 0.1)
    p.totals = {"boss": 10.3, "total": 6.8}
    d.optimized = [p]
    text = "\n".join(headline(d))
    assert "Boss damage: +10.3%" in text and "pad +6.8%" in text
    assert "Ascendance, Vile Vial: keep for Venomous Heart if it comes within 60 s" in text
    assert "Stormkeeper: only on add waves" in text
    assert "trinket1" not in text and "secondary" not in text and "hold vulnerable" not in text


def test_raid_section_and_headline():
    from paf.prep_report import RaidInfo
    from paf.raidneed import AOE, AddType, verdicts

    t = AddType("Amani", 100, 18.0, 0.15, {"Balance Druid": 0.44}, 0.25, tops_rate=1000.0, tops_low=900.0)
    vs = verdicts([t], [("Balance Druid", 2500.0)], ("Elemental Shaman", 1000.0))
    d = PrepData("Boss", "mythic", "Elemental", "Char")
    d.raid = RaidInfo("AbCdEf1234567890", "this boss, kill of 7:28", 20, ("Elemental Shaman", 190e3), False, vs,
                      "boss", [], {AOE: ["Nizae (Balance Druid)"]}, "AoE / funnel")
    assert headline(d)[0].startswith("With your raid: stay on the boss.")
    page = render(d)
    assert "Your raid and the adds" in page and "Nizae (Balance Druid)" in page and "you are not in that log" in page


def test_render_prep_sheet_with_wowhead_links():
    d = PrepData("Boss <X>", "heroic", "Elemental", "Char", kills=10, duration=300)
    d.gear = [("shoulder: Hissing Mantle (321)", {"boss fight": 1.0}, 1.0)]
    d.gear_fights = ["boss fight"]
    d.loot = [("Soul Fang", "main_hand", 0.5, 0.8)]
    d.links = {"Hissing Mantle": "item=271481&ilvl=321", "Soul Fang": "item=271092&ilvl=321"}
    page = render(d)
    body = page.split("<main>", 1)[1].split("<script>", 1)[0]
    assert "{" not in body  # no unformatted template left
    assert 'class="tabs"' in page and 'id="change"' in page and 'id="deeper"' in page
    assert "Boss &lt;X&gt;" in page and "Best gear from your bags" in page
    assert 'data-wowhead="item=271481&amp;ilvl=321"' in page and 'href="https://www.wowhead.com/item=271092"' in page
    assert "wow.zamimg.com/js/tooltips.js" in page


def test_checklist():
    d = PrepData("Boss", "heroic", "Elemental", "Char")
    d.lust = 120
    d.role_bullets = ["Kill the Clutch.", "Burst the Heart."]
    d.assigns = ["Malice: interrupt"]
    d.waves = [(60.0, 4, 20.0, "Clutch")]  # adds: pad them or not is the raid's call
    page = render(d)
    assert "Once the pull starts" in page and "Bloodlust usually comes around 2:00" in page
    assert "Kill the Clutch." in page and "Your assignment: Malice: interrupt" in page
    assert "ask your raid lead" in page


def test_goal_chosen_by_the_player():
    from paf.optimize import Plan, Rule

    d = PrepData("Boss", "heroic", "Elemental", "Char")
    d.goal = "boss"
    p = Plan("boss", {"ascendance": Rule("hold_adds_20", "", lambda o: o)}, 5.0, 0.1)
    p.totals = {"boss": 5.0}
    d.optimized = [p]
    page = render(d)
    assert "Your role (your choice): <b>boss damage first</b>" in page and "your choice</span>" in page


def test_notes_read_in_time_order():
    from paf.prep_report import in_time_order

    mrt = "head\n{time:3:00} Shadow Blades\n{time:0:09} Defensive: Feint\n"
    assert in_time_order(mrt) == "head\n{time:0:09} Defensive: Feint\n{time:3:00} Shadow Blades\n"
    nsrt = "EncounterID:1\ntime:90.7;ph:1;tag:x\ntime:28.6;ph:2;tag:x\ntime:9.2;ph:1;tag:x\ntime:13.9;ph:1.5;tag:x"
    assert in_time_order(nsrt).splitlines()[1:] == ["time:9.2;ph:1;tag:x", "time:90.7;ph:1;tag:x",
                                                     "time:13.9;ph:1.5;tag:x", "time:28.6;ph:2;tag:x"]


def test_a_damage_taken_window_the_sims_leave_out_is_said():
    from paf.prep_report import unsimmed_amps

    d = PrepData("Sszorak", "heroic", "Elemental", "Char")
    d.role_bullets = ["Dig In increases Sszorak's damage taken during Howling Maelstrom.",
                      "Corroding Venom increases the tank's damage taken."]  # a player's damage taken: not a window
    assert unsimmed_amps(d) == ["Dig In"]
    assert "Dig In is not in the sims" in render(d)


def test_a_long_cooldown_off_the_top_players_moment_is_flagged():
    from types import SimpleNamespace

    from paf.prep_report import off_tops

    d = PrepData("Nek'zali", "heroic", "Subtlety", "X", duration=240)
    d.tops_players = 20
    d.tops_casts = {"shadow_blades": [0.5] * 20 + [96 + i % 5 for i in range(15)] + [190] * 18,
                    "symbols_of_death": [t + i for t in range(0, 240, 30) for i in range(20)]}
    p = SimpleNamespace(timeline=[(0, "shadow blades"), (90, "shadow blades"), (180, "shadow blades"),
                                  (2, "symbols of death"), (40, "symbols of death"), (70, "symbols of death")])
    assert off_tops(d, p) == ["Shadow Blades: the plan presses it at 1:30, 75% of the top players at about 1:38.",
                              "Shadow Blades: the plan presses it at 3:00, 90% of the top players at about 3:10."]


def test_gear_and_loot_inside_the_noise_get_one_verdict_and_no_colour():
    # Subtlety Rogue, Vashnik (DPS round 10): the best set +0.57% at ±0.29% "≈ keep yours", the sets under it
    # "≈ best"; a drop at +0.31% green with ±0.20%
    d = PrepData("Vashnik", "heroic", "Subtlety", "Char", kills=10, duration=240)
    d.gear = [("trinket: A (334)", {"boss fight": 0.57}, 0.57), ("chest: B (321)", {"boss fight": 0.45}, 0.45)]
    d.gear_fights, d.gear_error = ["boss fight"], 0.29
    d.loot, d.loot_error = [("Sanguine Rancor", "trinket", 0.31, -0.15)], 0.20
    page = render(d)
    assert page.count("keep yours</span>") == 1 and "&asymp; best</span>" not in page
    assert "&asymp; best: within" not in page
    assert '<span class="">+0.31%</span>' in page and '<span class="pos">' not in page.split("What this boss drops")[1]


def test_a_plan_not_played_keeps_its_own_notes_on_its_card():
    # Subtlety Rogue, Vashnik (DPS round 11): the pad card's MRT note was the default list's (potion 0:02) beside
    # the plan's NSRT times (potion 1:48)
    from paf.optimize import Plan, Rule

    d = PrepData("Vashnik", "heroic", "Subtlety", "Char", kills=10, duration=240)
    d.goal = "total"
    d.optimized = [Plan("total", {"potion": Rule("hold_adds_60", "", None)}, 0.6, 0.1, sensitivity={"slower": -0.4},
                        timeline=[(108.0, "potion")], default_timeline=[(2.0, "potion")])]
    d.mrt = {"total": "prep-a-fight: Vashnik, cooldowns for total damage (pad) (+0.6%)\n{time:1:48} Potion"}
    page = render(d)
    assert "{time:1:48} Potion" in page and "{time:0:02} Potion" not in page.split("not played")[1]


def test_a_mechanics_times_find_its_name_in_a_wowhead_link():
    """Round 37: the boss tab's 'around' times of the mechanics were lost once the names became Wowhead links."""
    from types import SimpleNamespace

    from paf.prep_report import mech_around

    html = ('<div class="ab"><div><b><a class="wh" href="x">Essence Rend</a></b> </div>'
            "<div class='small muted'>11 players hit per kill</div></div>")
    d = SimpleNamespace(boss_casts=[], mech_times={"Essence Rend": [20.0, 60.0]})
    assert "around 0:20, 1:00" in mech_around(html, d)


def test_two_gains_that_round_alike_get_two_decimals():
    from paf.prep_report import places

    assert places(6.56, [6.56, 6.64]) == 2 and places(6.64, [6.56, 6.64]) == 2  # both "+6.6%" at one decimal
    assert places(6.56, [6.56, 3.1]) == 1 and places(6.56, [6.56, 6.561]) == 1  # the same figure: one
