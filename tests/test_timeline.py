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


def test_recurring_casts_keep_each_one_when_the_kills_drift():
    from paf.corpus.timeline import ordinal_times

    # Soul Transfer: the 1st cast drifts from 1:28 to 2:04 across kills, the next ones follow it (clustering the raw
    # times made one cast of the three); two units casting at once count once
    kills = [[88, 96, 133], [97, 105, 140], [124, 124.5, 132, 179], [93, 101, 138], [105, 113, 157]]
    assert ordinal_times(kills) == [97, 105, 140]
    assert ordinal_times([[10], [10, 60], [10, 60, 120]]) is None  # the count varies: no ordinal reading


def test_a_last_stage_that_loops_back_becomes_windows():
    from paf.corpus.timeline import looped_phases

    casts = [("Mutilate", [9, 61, 151, 199]), ("Ravage", [12.5, 64.7, 146.7, 202.9]), ("Tempest", [17, 69.3, 155.2]),
             ("Venomous Surge", [32.2, 84.4, 170.3]), ("Dig In", [111.1, 249.2])]
    phases = [("Sszorak", 0.0), ("Howling Maelstrom", 111.1)]
    assert looped_phases(phases, casts, 275) == [("Sszorak", 0.0), ("Howling Maelstrom", 111.1), ("Sszorak", 138.2),
                                                 ("Howling Maelstrom", 249.2)]
    real = [("Stage One", 0.0), ("Intermission", 97.3), ("Stage Two", 152.1)]  # stages that do not come back
    assert looped_phases(real, [("Invoke", [170.0]), ("Ritual Burn", [3, 76, 170])], 240) == real


def test_an_intermission_that_comes_back_with_the_immunity():
    from paf.corpus.timeline import immune_phases

    phases = [("Stage One: Entombed Sentinels", 0.0), ("Intermission: Vitriolic Stasis", 46.3)]
    immune = [(46.2, 10.5), (147.6, 11.5), (250.3, 8.0)]
    assert immune_phases(phases, immune) == [
        ("Stage One: Entombed Sentinels", 0.0), ("Intermission: Vitriolic Stasis", 46.2),
        ("Stage One: Entombed Sentinels", 56.7), ("Intermission: Vitriolic Stasis", 147.6),
        ("Stage One: Entombed Sentinels", 159.1), ("Intermission: Vitriolic Stasis", 250.3),
        ("Stage One: Entombed Sentinels", 258.3)]
    nek = [("Stage One", 0.0), ("Intermission", 101.6), ("Stage Two", 160.0)]  # one immunity: unchanged
    assert immune_phases(nek, [(101.6, 58.4)]) == nek
