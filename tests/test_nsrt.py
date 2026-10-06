from paf.fight import Fight
from paf.optimize import Plan, nsrt_note, nsrt_phase

PHASES = [("Stage One", 0.0), ("Intermission", 158.0), ("Stage Two", 261.0)]


def test_nsrt_phases():
    assert nsrt_phase(3470, PHASES, 100) == (1, 100)
    assert nsrt_phase(3470, PHASES, 170) == (1.5, 12)  # Nek'zali: the intermission is NSRT phase 1.5
    assert nsrt_phase(3470, PHASES, 300) == (2, 39)
    assert nsrt_phase(3492, PHASES, 300) == (1, 300)  # a boss NSRT does not split: from the pull
    assert nsrt_phase(3445, PHASES, 300) == (3, 39)  # "order"
    assert nsrt_phase(3497, PHASES, 100) == (1, 100) and nsrt_phase(3497, PHASES, 200)[0] == 0  # "first"


def test_nsrt_note_lines():
    timeline = [(10.0, "ascendance"), (270.0, "ascendance"), (270.5, "lightspire core")]
    plan = Plan("total", {}, 6.2, 0.3, timeline=timeline)
    note = nsrt_note(3470, plan, Fight("Boss", 400), PHASES, "Ixuu", {"ascendance": 114050},
                     {"trinket1": "Lightspire Core"})
    lines = note.splitlines()
    assert lines[0] == "EncounterID:3470"
    assert "time:10.0;ph:1;tag:Ixuu;spellid:114050;dur:5" in lines
    assert "time:9.0;ph:2;tag:Ixuu;spellid:114050;dur:5" in lines
    assert any(x.startswith("time:9.0;ph:2;tag:Ixuu;text:Lightspire Core") for x in lines)


def test_nsrt_skips_reminders_nsrt_would_clear():
    plan = Plan("total", {}, 6.2, 0.3, timeline=[(170.0, "ascendance"), (240.0, "ascendance")])
    lines = nsrt_note(3470, plan, Fight("Boss", 400), PHASES, "Ixuu", {"ascendance": 114050}).splitlines()
    assert "time:12.0;ph:1.5;tag:Ixuu;spellid:114050;dur:5" in lines
    assert not any("time:82" in x for x in lines) and "not placed" in lines[-1] and "4:00" in lines[-1]
    assert "time:" not in lines[-1] and "tag:" not in lines[-1]
