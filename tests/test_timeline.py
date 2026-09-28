from paf.corpus.timeline import Ability, Timeline, render_html


def test_render_html_contains_rows_and_escapes_names():
    tl = Timeline(
        boss="Boss <X>", difficulty="heroic", spec="Elemental", kills=3, duration=300,
        phases=[("Stage One: A", 0, False), ("Intermission", 120, True)],
        waves=[(60.0, 3, 20.0, "Add")],
        abilities=[Ability(1, "Ascendance", 1.0, 3, "#e8590c"), Ability(2, "Ghost Wolf", 1.0, 4, "#1c7ed6", True)],
        players=[{"rank": 1, "dps": 300000, "ilvl": 320, "duration": 300, "casts": {1: [5.0, 125.0], 2: [60.0]}}],
        boss_casts=[("Big Hit", [30.0, 90.0])],
    )
    page = render_html(tl)
    assert "Boss &lt;X&gt;" in page
    assert page.count("<circle") == 2  # utility abilities are not drawn on player rows
    assert "Big Hit" in page and "Defensives, movement and utility" in page
