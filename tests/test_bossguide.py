from paf.bossguide import abilities_html, bullets, summary_html
from paf.mechanics import Section


def sec(id_, title, kind, text="", flags=(), spell=0, children=()):
    s = Section(id_, title, kind, spell, list(flags), text, 0, id_, -1)
    s.children = list(children)
    return s


def test_bullets():
    assert bullets("- Kill the spawns. - Soak the waves.") == ["Kill the spawns.", "Soak the waves."]


def test_summary_and_abilities():
    over = sec(1, "Overview", "overview", "She splashes venom.", children=[
        sec(2, "Damage Dealers", "overview", "- Kill the Clutch. - Burst the Heart.", ["damage"]),
        sec(3, "Tank", "overview", "- Taunt on Mother's Wrath.", ["tank"])])
    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Venomous Heart", "ability", "The heart is exposed.", ["damage"], 1299526),
        sec(6, "Malice", "ability", "A bolt.", ["interruptible", "deadly"], 1290779)])
    s = summary_html([over, stage], "damage")
    assert "She splashes venom." in s and "<li>Burst the Heart.</li>" in s
    assert "<b>Tank:</b> Taunt on Mother&#x27;s Wrath." in s

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
    assert "A corpse lingers." not in second and "as in Stage One, now deadly" in second  # only the new tag


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
    assert "Pulls several players in." in a and "A well of necrotic energy." in a
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
    assert "as in Stage One, now deadly" in inter and "A corpse lingers." not in inter
    assert "Also, as in Stage One: Corpse Blight." in inter


def test_another_difficultys_sentences_are_left_out():
    """Vashnik heroic (2026-10-20): the journal's "On Mythic difficulty, ..." abilities showed on a heroic sheet, and
    "absorbs the next X healing" kept its game variable."""
    from paf.bossguide import readable

    stage = sec(4, "Stage One", "stage", children=[
        sec(5, "Siphoning Infection", "ability", "A blood venom that absorbs the next X healing."),
        sec(6, "Exploding Infection", "ability", "On Mythic difficulty, this gains a stack every 1.5 sec."),
        sec(7, "Imbibe", "ability", "Vashnik drinks. On Mythic difficulty, Imbibe conjures a totem.")])
    heroic = abilities_html([stage], difficulty="heroic")
    assert "absorbs the next healing" in heroic and "Exploding Infection" not in heroic
    assert "Vashnik drinks." in heroic and "conjures a totem" not in heroic
    assert "Exploding Infection" in abilities_html([stage], difficulty="mythic")
    assert readable("On Heroic difficulty, the rite burns.", "normal") == ""
