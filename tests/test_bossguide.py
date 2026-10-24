from paf.bossguide import abilities_html, bullets, summary_html
from paf.mechanics import Section

NOW_DEADLY = 'as in Stage One, now</span> <span class="pill warn">deadly</span>'  # the pill, as every ability


def sec(id_, title, kind, text="", flags=(), spell=0, children=()):
    s = Section(id_, title, kind, spell, list(flags), text, 0, id_, -1)
    s.children = list(children)
    return s


def test_bullets():
    assert bullets("- Kill the spawns. - Soak the waves.") == ["Kill the spawns.", "Soak the waves."]


def test_summary_and_abilities():
    over = sec(1, "Overview", "overview", "She splashes venom.", children=[
        sec(2, "Damage Dealers", "overview", "- Kill the Clutch. - Burst the Heart.", ["damage"]),
        sec(3, "Tank", "overview", "- Taunt on Malice.", ["tank"])])
    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Venomous Heart", "ability", "The heart is exposed.", ["damage"], 1299526),
        sec(6, "Malice", "ability", "A bolt.", ["interruptible", "deadly"], 1290779)])
    s = summary_html([over, stage], "damage")
    assert "She splashes venom." in s and "<li>Burst the Heart.</li>" in s
    # another role: not here; the ability list names theirs from the journal's flags (round 37: two lists)
    assert "Tank:" not in s and "Taunt on" not in s

    class Mech:
        name, kind, players_per_kill, cost = "Malice", "interrupt", 0, 1.0

    a = abilities_html([over, stage], timings={"Venomous Heart": [120.0, 271.0]}, mechanics=[Mech()],
                       burst={"Venomous Heart": 2.0})
    assert "Stage One" in a and "Overview" not in a
    assert "around 2:00, 4:31" in a and "boss takes x2 damage" in a
    assert "interrupted, ~1 s of movement for you" in a and ">interrupt</span>" in a


def test_a_stage_names_what_it_repeats():
    """Nek'zali's Stage Two repeats Stage One's abilities word for word: named once, not described twice; one that
    changes (a new flag) is described again."""
    well = sec(5, "Soulcoil Well", "ability", "A well of necrotic energy.", children=[
        sec(6, "Soulcoil Rite", "ability", "The rite's power afflicts players.")])
    rage = sec(7, "Uncoiled Rage", "ability", "She gains her full potential.", ["deadly"])
    one = sec(4, "Stage One", "stage", children=[well, rage, sec(8, "Vessel", "ability", "A corpse lingers.")])
    two = sec(9, "Stage Two", "stage", children=[
        sec(10, "Soulcoil Well", "ability", "A well of necrotic energy.", children=[
            sec(11, "Soulcoil Rite", "ability", "The rite's power afflicts players.")]),
        sec(12, "Uncoiled Rage", "ability", "She gains her full potential.", ["deadly"]),
        sec(13, "Vessel", "ability", "A corpse lingers.", ["deadly"]),
        sec(14, "Invoke", "ability", "She calls the cultists.")])
    a = abilities_html([one, two])
    second = a[a.index("Stage Two"):]
    assert "Also, as in Stage One: Soulcoil Well, Soulcoil Rite, Uncoiled Rage." in second
    assert "A well of necrotic energy." not in second and "She calls the cultists." in second
    assert "A corpse lingers." not in second and NOW_DEADLY in second  # only the new tag


def test_another_roles_abilities_are_named_not_told():
    """A damage dealer's journal: Nek'zali's tank abilities (Possession Barrage, and what sits under it) are named at
    the stage's end; the abilities of no role or of the damage dealers stay in full."""
    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Essence Rend", "ability", "Pulls several players in.", ["damage"]),
        sec(6, "Possession Barrage", "ability", "Echoes burst on impact.", ["tank"], children=[
            sec(7, "Spectral Echo", "ability", "An echo of her soul.")]),
        sec(8, "Soulcoil Ignition", "ability", "Raid damage.", ["healer"]),
        sec(9, "Soulcoil Well", "ability", "A well of necrotic energy.")])
    a = abilities_html([stage], role="damage")
    # your role's ability told; one the journal flags for no role: its name only, a link to read it (the owner)
    assert "Pulls several players in." in a and "A well of necrotic energy." not in a and "Soulcoil Well" in a
    assert "Echoes burst on impact." not in a and "An echo of her soul." not in a
    assert "For the tanks: Possession Barrage." in a and "For the healers: Soulcoil Ignition." in a
    assert "Echoes burst on impact." in abilities_html([stage])  # no role (the sheet's boss tab): everything


def test_a_unit_told_before_shows_only_what_changes():
    """Nek'zali's intermission repeats the Restless Amani of Stage One, with Vessel of Awakening now deadly: the unit
    is named with "As in Stage One", the changed ability told, the others named."""
    def amani(base, deadly):
        return sec(base, "Restless Amani", "creature", "Ancient spirits return to their corpses.", children=[
            sec(base + 1, "Vessel of Awakening", "ability", "A corpse lingers.", ["deadly"] if deadly else []),
            sec(base + 2, "Corpse Blight", "ability", "Plague damage to all players.")])
    one = sec(1, "Stage One", "stage", children=[amani(2, False)])
    two = sec(10, "Intermission", "stage", children=[amani(11, True)])
    a = abilities_html([one, two])
    inter = a[a.index("Intermission"):]
    assert "As in Stage One; what changes:" in inter and "Ancient spirits" not in inter
    # under the unit's "As in Stage One", its rows say only what changed (round 38: three times in four lines)
    assert 'now</span> <span class="pill warn">deadly</span>' in inter and NOW_DEADLY not in inter
    assert "A corpse lingers." not in inter
    assert "Also unchanged: Corpse Blight." in inter  # the unit's line says the stage (round 39)


def test_another_difficultys_sentences_are_left_out():
    """Vashnik heroic (2026-10-20): the journal's "On Mythic difficulty, ..." abilities showed on a heroic sheet, and
    "absorbs the next X healing" kept its game variable."""
    from paf.bossguide import readable

    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Siphoning Infection", "ability", "A blood venom that absorbs the next X healing."),
        sec(6, "Exploding Infection", "ability", "On Mythic difficulty, this gains a stack every 1.5 sec."),
        sec(7, "Imbibe", "ability", "Vashnik drinks. On Mythic difficulty, Imbibe conjures a totem.")])
    heroic = abilities_html([stage], difficulty="heroic")
    assert "absorbs an amount of incoming healing" in heroic and "gains a stack" not in heroic
    assert "Exploding Infection" in heroic  # it exists at heroic too (dispelled 4 times a kill): its name stays
    assert "Vashnik drinks." in heroic and "conjures a totem" not in heroic
    assert "gains a stack" in abilities_html([stage], difficulty="mythic")
    assert readable("On Heroic difficulty, the rite burns.", "normal") == ""


def test_another_roles_ability_that_hits_you_is_told():
    """Vashnik heroic: Toxic Vapor is tagged for the healers but makes 11% of the damage the top tanks take: on the
    tank's sheet it is told in full, with that number."""
    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Toxic Vapor", "ability", "A cloud of venom.", ["healer"])])
    a = abilities_html([stage], role="tank", also={"Toxic Vapor": "11% of the damage the top tanks take"})
    assert "A cloud of venom." in a and "11% of the damage the top tanks take" in a and "For the healers" not in a


def test_a_stage_heading_says_when_it_starts():
    # Nek'zali (round 79): "Intermission: Ritual of Awakening" with no time, the chart draws its line
    one = sec(1, "Stage One: Soulcoiler Initiation", "stage", children=[sec(3, "Soulcoil Rite", "ability", "Hits.")])
    two = sec(2, "Intermission: Ritual of Awakening", "stage", children=[sec(4, "Ritual Burn", "ability", "Burns.")])
    out = abilities_html([one, two], phases=[("Stage One", 0.0), ("Intermission", 110.0)])
    assert "Stage One: Soulcoiler Initiation <span class='muted small'>from the pull</span>" in out
    assert "Intermission: Ritual of Awakening <span class='muted small'>from about 1:50</span>" in out


def test_journal_times_round_as_the_page_header():
    # app round 14: "Restless Amani around 0:52" under a header and plan box saying 0:53 (52.7 s)
    from paf import bossguide

    assert bossguide._when([52.7, 167.0]) == "0:52, 2:47"  # the fight tab's and the MRT notes' form


def test_what_hits_you_too_stays_told_in_every_stage():
    """Review 36: the stage notes reused the name of `also`, so from Stage Two Possession Barrage (the tank's, a big
    raid hit too) was named 'For the tanks' on a healer's sheet."""
    s1 = sec(4, "Stage One", "stage", children=[sec(5, "Possession Barrage", "ability", "Echoes burst.", ["tank"])])
    s2 = sec(6, "Stage Two", "stage", children=[sec(7, "Possession Barrage", "ability", "Echoes burst too.", ["tank"])])
    a = abilities_html([s1, s2], role="healer", also={"Possession Barrage": "big raid damage at 3:50"})
    assert "For the tanks" not in a and "Echoes burst too." in a


def test_a_healers_dispels_are_told_what_their_summary_names_tagged():
    over = sec(1, "Overview", "overview", children=[sec(2, "Healers", "role", "- Imbibe inflicts heavy damage.")])
    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Essence Rend", "ability", "A magic curse on a player.", ["magic"]),
        sec(6, "Imbibe", "ability", "The boss drinks."),
        sec(7, "Plague Froth", "ability", "Froth.")])
    a = abilities_html([over, stage], role="healer")
    # the dispel told; what the healers' summary names: their tag, its words being the summary's (round 37)
    assert "A magic curse on a player." in a and ">magic<" in a and "Froth." not in a
    assert "The boss drinks." not in a and "&uarr; for you</span>" in a


def test_a_mechanic_that_lands_on_players_is_told():
    """Round 37: Exploding Infection (9 players a kill) lost its words with decision 1; it can be you."""
    class Mech:
        name, kind, players_per_kill, cost = "Exploding Infection", "debuff", 9.0, 0.0
    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Exploding Infection", "ability", "Erupts on nearby players.", ["magic"]),
        sec(6, "Plague Froth", "ability", "Froth.")])
    a = abilities_html([stage], role="damage", mechanics=[Mech()])
    assert "Erupts on nearby players." in a and "Froth." not in a


def test_an_ability_the_summary_names_in_passing_is_marked_not_told_twice():
    """Rounds 39-40: Sanguineous Fortitude, named in passing by the DPS summary and flagged dps, told its words
    again; Malignant Burst, named in passing, a bare name. Both: the marker, no words."""
    over = sec(1, "Overview", "overview", children=[sec(2, "Damage Dealers", "overview",
               "- Clotting Venom is protected by Sanguineous Fortitude. - Venoms explode in Malignant Burst.",
               ["damage"])])
    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Sanguineous Fortitude", "ability", "Fortified as it emerges.", ["damage"]),
        sec(6, "Malignant Burst", "ability", "Bursts on all players.", ["deadly"])])
    a = abilities_html([over, stage], role="damage")
    # flagged for the role and named in passing: its own words say more than the line (round 41: Toxic Vapor)
    assert "Fortified" in a and ">dps<" in a and "Bursts on all" not in a and a.count("&uarr; for you") == 1
