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
    assert "Ascendance, Vile Vial: hold for Venomous Heart if within 60 s" in text
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
    assert "Your raid and the adds" in page and "title='Balance Druid'" in page and "you are not in that log" in page


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


def test_dig_deeper_leaves_out_what_the_other_tabs_say():
    """The owner's clean-up: no "What matters for you" (What to change says it), no "Once the pull starts" (The boss
    and the fight tab say it), no tiles of your character (the aim tiles say them); the assignments stay."""
    d = PrepData("Boss", "heroic", "Elemental", "Char", duration=300)
    d.lust = 120
    d.role_bullets = ["Kill the Clutch.", "Burst the Heart."]
    d.assigns = ["Malice: interrupt"]
    d.waves = [(60.0, 4, 20.0, "Clutch")]
    d.sim_dps, d.sim_boss_dps, d.patchwerk_dps = 200000.0, 150000.0, 210000.0
    page = render(d)
    assert "Once the pull starts" not in page and "What matters for you" not in page
    assert "Your character on this fight" not in page
    assert "Your assignments and plan" in page and "Malice: interrupt" in page


def test_the_rebuilt_fight_shows_the_simmed_column_only_when_it_differs():
    from paf.fight import AddWave, Fight

    d = PrepData("Boss", "heroic", "Elemental", "Char", duration=300)
    d.waves = [(60.0, 4, 20.0, "Clutch")]
    d.fight = Fight("Boss", 300, add_waves=[AddWave(60.0, 4, 20.0, name="Clutch")])
    d.export = {"": "fight_style=x\nraid_events+=/adds,count=4"}
    page = render(d)
    assert "The rebuilt fight" in page and "Simmed</th>" not in page and "Sim this fight on Raidbots" not in page
    assert "Copy the fight" in page.split("The rebuilt fight", 1)[1].split("</section>", 1)[0]  # in its card
    d.add_scale = 0.5
    assert "Simmed</th>" in render(d)


def test_goal_chosen_by_the_player():
    from paf.optimize import Plan, Rule

    d = PrepData("Boss", "heroic", "Elemental", "Char")
    d.goal = "boss"
    p = Plan("boss", {"ascendance": Rule("hold_adds_20", "", lambda o: o)}, 5.0, 0.1)
    p.totals = {"boss": 5.0}
    d.optimized = [p]
    page = render(d)
    assert "your choice</span>" in page


def test_plans_that_change_nothing_are_one_line_and_nsrt_sits_beside_the_mrt_note():
    from paf.optimize import Plan, Rule

    d = PrepData("Boss", "heroic", "Elemental", "Char", duration=300)
    d.goal = "total"
    pad = Plan("total", {"ascendance": Rule("on_cooldown", "", None)}, 2.0, 0.1, totals={"total": 2.0, "boss": -1.0},
               timeline=[(5.0, "Ascendance")])
    boss = Plan("boss", {"ascendance": Rule("default", "", None)}, 0.0, 0.1, totals={"boss": 0.0})
    d.optimized = [pad, boss]
    d.mrt = {"total": "prep-a-fight: Boss\n{time:0:05} Ascendance"}
    d.nsrt = {"total": "EncounterID:1\ntime:5;ph:1;tag:x;spellid:1;dur:5"}
    deeper = render(d).split('id="deeper"', 1)[1]
    assert "<b>Boss damage:</b> no plan beats SimC's default list" in deeper
    assert "Boss damage: <span" not in deeper  # no card of 0.0%
    assert "Northern Sky Raid Tools reminders" not in deeper  # its button in the MRT note's heading
    head = deeper.split("MRT note", 1)[1].split("</h4>", 1)[0]
    assert "Copy the MRT note" in head and "Copy for NSRT" in head


def test_talents_that_all_lose_show_the_verdict_and_three_builds():
    from pathlib import Path

    from paf.talent_sim import Build, TalentComparison, TalentRow

    d = PrepData("Boss", "mythic", "Subtlety", "Char", duration=300)
    names = [f"T{i}" for i in range(40)]
    rows = [TalentRow(Build(frozenset({i}), n=5, rank=50.0), {"boss fight": (-3.0 - i, -8.0 - i)}, names, [])
            for i in range(6)]
    d.talents = TalentComparison(["boss fight"], rows, 0.1, Path("."))
    table = render(d).split("Talents of the top players", 1)[1].split("</table>", 1)[0]
    assert "Keep your talents" in table and table.count("players, median rank") == 3
    assert table.count("on the boss") == 1  # under the best build only
    assert "other-build" not in table and "<span class='muted'>other build &middot; 40 talents apart" in table


def test_the_boss_tab_says_facts_in_plain_words_and_a_unit_once():
    from paf.actions import Action

    d = PrepData("Boss", "mythic", "Subtlety", "Char", duration=380)
    d.guide_summary = ("<div class=\"guide\"><h3>For you, as a damage dealer</h3><ul><li>Dodge the pools.</li></ul>"
                       "<h3>The fight</h3><div class='over'><p>The twins hunt together.</p></div></div>")
    d.actions = [Action("kill", "Spawn", "Kill the Spawn (~14 per kill): the top raids kill them in ~11 s; top "
                        "Subtlety players put 49% of their damage on them while they are up."),
                 Action("assignment", "Vile Flood", "Vile Flood: 3 players per kill, an assignment. If it is yours, "
                        "tick it in the app (the boss's prep page)."),
                 Action("mechanic", "Noxious Slick", "Noxious Slick: hits ~5 players per kill; top Subtlety players "
                        "take it in 45% of the kills: it can be you.")]
    d.waves = [(0.0, 1, 140.0, "Ithraz"), (35.0, 3, 11.0, "Spawn"), (147.0, 1, 150.0, "Ithraz"),
               (302.0, 1, 78.0, "Ithraz")]
    boss = render(d).split('id="boss"', 1)[1].split("</section>", 1)[0]
    assert "Dodge the pools." in boss and "The twins hunt together." not in boss  # the "For you" list only
    assert "tick it" not in boss and "class='pill'" not in boss  # facts as muted words, no page to go to
    assert "you in 45% of the kills: it can be you" in boss
    assert boss.count(">Ithraz") == 1 and "at 0:00, 2:27, 5:02" in boss and "up 78&ndash;150 s" in boss


def test_nothing_to_change_offers_no_plan_it_does_not_play():
    from paf.optimize import Plan, Rule

    d = PrepData("Boss", "mythic", "Subtlety", "Char", duration=300)
    d.goal = "total"
    p = Plan("total", {"vanish": Rule("on_cooldown", "", None)}, 0.6, 0.1, totals={"total": 0.6, "boss": -1.1},
             sensitivity={"slower": -0.4}, timeline=[(5.0, "Vanish")], default_timeline=[(2.0, "Vanish")])
    d.optimized = [p]
    d.mrt = {"total": "prep-a-fight: Boss\n{time:0:05} Vanish"}
    change = render(d).split('id="change"', 1)[1].split("</section>", 1)[0]
    assert "Nothing to change" in change and "Copy the MRT note" not in change  # Dig deeper keeps it


def test_only_the_plan_the_fight_tab_plays_can_be_copied():
    # The Twin Fangs, Subtlety (a fresh review): the pad plan, not played, kept its copy buttons; the adds plan, not
    # robust either, had no pill at all
    from paf.optimize import Plan, Rule

    d = PrepData("Boss", "mythic", "Subtlety", "Char", duration=300)
    d.goal = "total"
    pad = Plan("total", {"vanish": Rule("on_cooldown", "", None)}, 0.6, 0.1, totals={"total": 0.6},
               sensitivity={"slower": -0.4}, timeline=[(5.0, "Vanish")], default_timeline=[(2.0, "Vanish")])
    adds = Plan("adds", {"shadow_blades": Rule("on_cooldown", "", None)}, 6.1, 0.1, totals={"adds": 6.1},
                sensitivity={"slower": -0.5}, timeline=[(5.0, "Shadow Blades")])
    d.optimized = [pad, adds]
    d.mrt = {"total": "prep-a-fight: Boss\n{time:0:05} Vanish", "adds": "prep-a-fight: Boss\n{time:0:05} Shadow Blades"}
    d.nsrt = {"total": "EncounterID:1\ntime:5;ph:1;tag:x;spellid:1;dur:5"}
    plans = render(d).split('id="deeper"', 1)[1].split("Cooldown plans, per objective</h2>", 1)[1].split("<h2", 1)[0]
    assert plans.count("not played: not robust") == 2 and "the sheet plays this plan" not in plans
    assert "Copy the MRT note" not in plans and "Copy for NSRT" not in plans
    assert "{time:0:05} Shadow Blades" not in plans  # a plan not played: one line, no note (a second fresh review)
    pad.sensitivity = {"slower": 0.5}  # robust, the raid's goal: played, the only card with the buttons
    plans = render(d).split('id="deeper"', 1)[1].split("Cooldown plans, per objective</h2>", 1)[1].split("<h2", 1)[0]
    assert plans.count("Copy the MRT note") == 1 and "the sheet plays this plan" in plans
    assert plans.count("not played: not robust") == 1


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
    # the threshold the colours use, twice the error, said as is (a review: "+0.56% ±0.29, within the noise")
    assert "<b>Keep yours:</b> the best swap, trinket: A (334), is +0.57%, under the &plusmn;0.58% noise." in page
    assert "Gain\n&plusmn;0.58%</th>" in page and "a gap under &plusmn;0.40% is noise" in page
    assert "keep yours</span>" not in page and "&asymp; best</span>" not in page  # the sentence says it once
    assert "&asymp; best: within" not in page
    assert '<span class="">+0.31%</span>' in page and '<span class="pos">' not in page.split("What this boss drops")[1]


def test_keep_yours_shows_three_sets_and_no_drop_is_said_plainly():
    d = PrepData("Boss", "mythic", "Subtlety", "Char", kills=10, duration=240)
    d.gear = [(f"chest: Set {i} (321)", {"boss fight": 0.5 - i / 10}, 0.5 - i / 10) for i in range(6)]
    d.gear_fights, d.gear_error = ["boss fight"], 0.29
    d.loot, d.loot_error = [("Amulet", "neck", -0.17, -0.43), ("Fang", "main_hand", -2.73, -3.34)], 0.18
    gear = render(d).split("Best gear from your bags", 1)[1].split("What this boss drops", 1)
    assert gear[0].count("gearset") == 3  # the top 3 sets only
    loot = gear[1].split("</section>", 1)[0]
    assert "notice" not in loot and "the closest, Amulet, is" in loot and "-0.43%" in loot


def test_a_plan_not_played_is_one_line_without_a_note():
    # Subtlety Rogue, Vashnik (DPS round 11): the pad card's note was the default list's; a second fresh review
    # (2026-11-15): a plan the sheet does not play shows no note at all, one line with its rules
    from paf.optimize import Plan, Rule

    d = PrepData("Vashnik", "heroic", "Subtlety", "Char", kills=10, duration=240)
    d.goal = "total"
    d.optimized = [Plan("total", {"potion": Rule("hold_adds_60", "", None)}, 0.6, 0.1, sensitivity={"slower": -0.4},
                        timeline=[(108.0, "potion")], default_timeline=[(2.0, "potion")])]
    d.mrt = {"total": "prep-a-fight: Vashnik, cooldowns for total damage (pad) (+0.6%)\n{time:1:48} Potion"}
    page = render(d)
    rest = page.split("Plans the sheet does not play")[1]
    assert "{time:1:48} Potion" not in rest and "{time:0:02} Potion" not in rest and "not played: not robust" in rest


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


def test_the_pad_verdict_draws_its_bar():
    from paf.prep_report import _pad_bar

    bar = _pad_bar("Pad them: with you, your raid does 53% of the top raids' damage on them (the weakest top raids "
                   "do 84%); it lacks cleave.")
    assert "width:53%" in bar and "left:84%" in bar
    # what it measures and who the mark is, in words (a review: "your raid 75%" beside a gold "93%")
    assert "Damage on the adds, as a share of the top raids' median" in bar
    assert ">your raid 53%</span>" in bar and ">weakest top raids 84%</span>" in bar and "warn" not in bar
    made = _pad_bar("pad them, you make the difference: your raid does 70% of the top raids' damage on them without "
                    "you, 90% with you (the weakest top raids do 84%)")
    assert "width:90%" in made and _pad_bar("Kill the adds.") == ""
    assert "width:53%" in _pad_bar("with you, your raid does 53% of the top raids&#x27; damage on them (the weakest "
                                   "top raids do 84%)")  # the card's details come escaped (round 43: never drawn)


def test_the_pad_line_leaves_its_shares_to_the_bar():
    from paf.prep_report import _without_shares

    assert _without_shares("Pad them: with you, your raid does 53% of the top raids&#x27; damage on them (the weakest "
                           "top raids do 84%); it lacks cleave.") == "Your raid lacks cleave."
    both = ("pad them, you make the difference: your raid does 70% of the top raids&#x27; damage on them without "
            "you, 90% with you (the weakest top raids do 84%).")
    assert _without_shares(both) == both  # the bar draws only the share with you


def test_the_adds_to_kill_render_as_a_table():
    """Fresh DPS review: the kill actions as a table; an Action is no set member (the first version crashed preps)."""
    from paf.actions import Action

    d = PrepData("Boss", "heroic", "Elemental", "Char", kills=10, duration=255)
    d.guide_summary = "<div class='guide'><p>x</p></div>"
    d.actions = [Action("kill", "Restless Amani", "Kill the Restless Amani (~21 per kill): the top raids kill them in "
                        "~19 s; top Elemental players put 23% of their damage on them while they are up."),
                 Action("kill", "Odd Add", "Kill the Odd Add whenever it comes.")]
    d.waves = [(52.0, 6, 18.0, "Restless Amani"), (73.0, 1, 75.0, "Echo of Jawae")]  # a unit no action names
    page = render(d)
    assert "Echo of Jawae</td><td class='n'>&times;1</td>" in page and "Kill the Echo of Jawae" not in page
    assert "<table class='kills fit'>" in page and "19 s" in page and "width:23%" in page
    # as many as the fight tab's waves of the median kill, not the mean of every kill (a review: x14 beside "15 adds")
    assert ">in 4:15</th>" in page and "Restless Amani</td><td class='n'>&times;6</td>" in page
    assert "Kill the Odd Add whenever it comes." in page  # a line the table cannot read keeps its words


def test_actions_read_as_a_short_muted_line():
    # Nek'zali, Elemental (fresh DPS review): the assignment, the mechanic and the unit left alive were sentences;
    # then uppercase pills carrying sentences (the owner's clean-up): a muted line, no page to go to
    from paf.actions import Action
    from paf.prep_report import action_row

    d = PrepData("Nek'zali", "heroic", "Elemental", "Char")
    well = action_row(d, Action("assignment", "Soulcoil Well", "Soulcoil Well: 4 players per kill, an assignment, "
                                "~4 s of movement when it is you. If it is yours, tick it in the app (the boss's prep "
                                "page)."))
    assert "<span class='act'" in well and "<b>Soulcoil Well</b>" in well
    assert "&#128101; 4 a kill &middot; ~4 s of movement when it is you: an assignment" in well
    assert "tick it" not in well and "pill" not in well
    rend = action_row(d, Action("mechanic", "Essence Rend", "Essence Rend: hits ~11 players per kill; top Elemental "
                                "players take it in 52% of the kills: it can be you."))
    assert "you in 52% of the kills: it can be you" in rend
    jawae = action_row(d, Action("ignore", "Summoner Jawae", "Summoner Jawae: the top raids do not kill it with "
                                 "damage (it stays ~3 min); do not spend your damage on it unless your raid's strategy "
                                 "says so."))
    assert "stays ~3 min" in jawae and "leave it" in jawae
    odd = action_row(d, Action("contact", "X", "X: handled by contact."))
    assert "X: handled by contact." in odd and "title=" not in odd


def test_a_unit_whose_cast_is_kicked_is_not_called_a_soak():
    # The Twin Fangs, Subtlety (a fresh review): "Units handled by contact (soak)" said the top raids do not damage
    # the Broodling while Interrupts said "Visceral Burst ~50 kicks a kill, your job" (its cast)
    from paf.actions import Action

    d = PrepData("The Twin Fangs", "mythic", "Subtlety", "Char", duration=366)
    d.guide_summary = "<div class='guide'><p>x</p></div>"
    brood = Action("contact", "Broodling", "Broodling: the top raids do not damage it; players get its debuffs "
                   "instead: Visceral Burst (~2 per kill). It is handled by contact (soak / breaking it), not by "
                   "damage.")
    kick = Action("interrupt", "Visceral Burst", "Interrupt Visceral Burst: top Subtlety players kick it in 34% of the "
                  "kills (~50 kicks per kill), far more than one player in twenty would: it is part of your job.")
    d.actions = [brood, kick]
    boss = render(d).split('id="boss"', 1)[1].split("</section>", 1)[0]
    assert "Units to kick, not kill" in boss and "(soak)" not in boss and "soak" not in boss
    assert "<b>Broodling</b> <span class='muted small'>kick its cast (Visceral Burst), don&#x27;t kill it" in boss
    d.actions = [brood]  # nobody kicks it: handled by contact, said shortly
    boss = render(d).split('id="boss"', 1)[1].split("</section>", 1)[0]
    assert "Units handled by contact (soak)" in boss and "Visceral Burst (~2 a kill): handled by contact" in boss
