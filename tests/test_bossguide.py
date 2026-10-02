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
    assert "She splashes venom." in s and "<li>Burst the Heart.</li>" in s and "<summary>Tank</summary>" in s

    class Mech:
        name, kind, players_per_kill, cost = "Malice", "interrupt", 0, 1.0

    a = abilities_html([over, stage], timings={"Venomous Heart": [120.0, 271.0]}, mechanics=[Mech()],
                       burst={"Venomous Heart": 2.0})
    assert "Stage One" in a and "Overview" not in a
    assert "around 2:00, 4:31" in a and "boss takes x2 damage" in a
    assert "interrupted, ~1 s of movement for you" in a and ">interrupt</span>" in a
