import pytest

from paf.fight import AddWave, Fight, Window
from paf.plan import all_offsets, apply_plan, parse_plan, parse_time, plan_template

TEXT = """
# my plan
2:45 move 6            # soak
5:30 move 8 shift -4..+4
4:10 move 4 distance 20
lust 0:30
pi 0:20 2:30
no boss-movement
"""


def fight():
    return Fight("Boss heroic", 300, add_waves=[AddWave(60, 3, 20, "Add")], movement=[Window(100, 5)])


def test_parse_time():
    assert parse_time("2:45") == 165
    assert parse_time("90") == 90.0
    with pytest.raises(ValueError):
        parse_time("2h")


def test_parse_plan():
    p = parse_plan(TEXT)
    assert [(m.start, m.duration, m.shiftable) for m in p.moves] == [(165, 6, False), (330, 8, True), (250, 4, False)]
    assert p.moves[2].distance == 20
    assert (p.lust, p.pi, p.keep_template_movement) == (30, [20, 150], False)


def test_parse_plan_errors_point_to_the_line():
    with pytest.raises(ValueError, match="line 2"):
        parse_plan("2:00 move 5\n3:00 jump 5\n")


def test_apply_plan_with_offsets():
    p = parse_plan(TEXT)
    f = apply_plan(fight(), p, {1: -4})
    assert f.movement == []  # template movement dropped
    assert [w.start for w in f.personal_movement] == [165, 326, 250]
    assert f.lust_time == 30 and f.power_infusion == [20, 150]
    assert fight().movement[0].start == 100  # the template is not modified


def test_offsets_grid_and_template():
    p = parse_plan(TEXT)
    assert [o[1] for o in all_offsets(p)] == [-4, -2, 0, 2, 4]
    assert "1:00  adds x3" in plan_template(fight())


def test_a_saved_plan_shows_the_current_template_and_keeps_the_players_lines():
    # app round 11: a plan saved on Oct 18 showed "4 players per kill; 4s moving" under a journal saying 5 and ~1 s
    from paf.fight import Fight, Window
    from paf.plan import mmss, refresh

    old = ("# Personal plan for X. Edit and save\n#   0:53  adds x6 for 18s (Old)\n2:45 move 6\n"
           "# assign Soulcoil Well   # 4 players per kill; 4s moving each time; at 0:05\nassign Essence Rend\n")
    f = Fight("X", 300.0, invulnerable=[Window(101.6, 58.0)])
    text = refresh(old, f)
    assert "Old" not in text and "4 players per kill" not in text and "1:41  boss not attackable for 58s" in text
    assert text.endswith("2:45 move 6\nassign Essence Rend\n")
    assert mmss(52.7) == "0:52" and mmss(59.6) == "0:59"  # as the MRT notes and the fight tab
