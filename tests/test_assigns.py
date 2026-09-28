from paf.assigns import Mechanic, apply_assigns, assigns_template
from paf.fight import Fight, Window
from paf.plan import parse_plan


def mechs():
    return [
        Mechanic("debuff:1", "Doomscale Shell", "debuff", [60.0, 180.0], 4.0, 8, 2),
        Mechanic("interrupt:2", "Malice", "interrupt", [30.0], 0.0, 0, 2),
    ]


def test_parse_assign_lines():
    p = parse_plan("assign Doomscale Shell  # my job\nassign Malice\n")
    assert p.assigns == ["Doomscale Shell", "Malice"]
    assert not p.empty


def test_apply_assigns_adds_movement_each_time():
    f = Fight("B", 300, movement=[Window(10, 3)])
    g, notes = apply_assigns(f, mechs(), ["doomscale shell", "Malice", "Nope"])
    assert [(w.start, w.duration) for w in g.movement] == [(10, 3)]
    assert [(w.start, w.duration) for w in g.personal_movement] == [(60, 4), (180, 4)]
    assert not f.personal_movement  # template untouched
    # personal moves are not scaled by the movement calibration
    g.movement_scale = 0.5
    events = [e for e in g.raid_event_lines() if "movement" in e]
    assert any("first=10" in e and "duration=1.5" in e for e in events)
    assert any("first=60" in e and "duration=4" in e for e in events)
    assert any("no measurable cost" in n for n in notes) and any("unknown" in n for n in notes)


def test_assigns_template_lists_commented_lines():
    text = assigns_template(mechs(), "Elemental")
    assert "# assign Doomscale Shell" in text and "kick" in text
