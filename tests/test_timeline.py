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


def test_target_segments_and_rows():
    from paf.corpus.timeline import target_kind, target_segments

    assert target_kind("Zul'jan", True, "zul'jan") == ""
    assert target_kind("Hex Lord", True, "Zul'jan") == "Hex Lord"
    assert target_kind("Soulcoiler", False, "Zul'jan") == "adds"
    casts = [(0.0, ""), (2.0, ""), (4.0, "Hex Lord"), (6.0, "Hex Lord"), (30.0, "adds")]
    assert target_segments(casts) == [(0.0, 5.5, ""), (4.0, 7.5, "Hex Lord"), (30.0, 31.5, "adds")]
    tl = Timeline(boss="Zul'jan", difficulty="heroic", spec="Elemental", kills=1, duration=60, phases=[], waves=[],
                  abilities=[], players=[{"rank": 1, "dps": 1, "ilvl": 1, "duration": 60, "casts": {},
                                          "targets": target_segments(casts)}])
    page = render_html(tl)
    assert "On Hex Lord" in page and "On adds" in page and "on Hex Lord" in page
