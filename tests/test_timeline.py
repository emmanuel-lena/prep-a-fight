from paf.corpus.timeline import Ability, Timeline, render_html


def test_plan_timeline_svg():
    from paf.fight import AddWave, Fight, Vulnerable
    from paf.optimize import Plan
    from paf.prep_report import plan_timeline_svg

    f = Fight("B", 300, add_waves=[AddWave(60, 5, 20)], vulnerable=[Vulnerable(120, 40, 2.0, "Heart")])
    p = Plan("boss", {}, 1.0, 0.1, timeline=[(0.0, "ascendance"), (122.0, "ascendance"), (5.0, "stormkeeper")])
    svg = plan_timeline_svg(p, f, {"ascendance": [3.0, 125.0, 126.0]}, tops_players=2)
    assert svg.count("<circle") == 3 and "x2" in svg and "top players: 2 casts" in svg


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
