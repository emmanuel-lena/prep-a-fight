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


def test_a_soak_is_taken_at_the_occurrences_you_tick():
    # the owner, 2026-11-12: Guillotine's soakers take turns ("you can't soak it twice"): soak the 1st, free at the 2nd
    from paf.assigns import Mechanic, apply_assigns, split_occurrences
    from paf.fight import Fight

    assert split_occurrences("Guillotine @1,3") == ("Guillotine", {1, 3})
    assert split_occurrences("Eternal Nightfall") == ("Eternal Nightfall", set())
    guillotine = Mechanic("debuff:1307425", "Guillotine", "debuff", [48.0, 133.0], 3.5, 10, 10.0)
    f, notes = apply_assigns(Fight("f", 300), [guillotine], ["Guillotine @1"])
    assert [(w.start, w.duration) for w in f.personal_movement] == [(48.0, 3.5)]
    assert notes == ["Guillotine: 3.5s of movement at 0:48"]
    f, _ = apply_assigns(Fight("f", 300), [guillotine], ["Guillotine"])  # an older plan's line: every one
    assert len(f.personal_movement) == 2


def test_the_boss_s_targets_are_no_assignment(monkeypatch):
    # the owner, 2026-11-12: "useless to list what the boss targets you with" (Dreadmarch); a soak leaves its mark
    from paf import assigns

    effects = {1307425: [{"Effect": "6", "EffectAura": "255"}],  # Guillotine's soakers: +500% from Guillotine
               1297445: [{"Effect": "6", "EffectAura": "69"}, {"Effect": "6", "EffectAura": "60"}]}  # Dreadmarch
    monkeypatch.setattr("paf.gamedata._filtered_rows", lambda table, col, spell: effects.get(spell, []))
    assert assigns.is_soak(1307425) is True and assigns.is_soak(1297445) is False


def test_ticked_soak_times_are_one_plan_line(tmp_path, monkeypatch):
    from paf import web

    monkeypatch.setenv("PAF_HOME", str(tmp_path))

    class Enc:
        id, name = 7, "Boss"

    monkeypatch.setattr("paf.encounters.raid_encounters", lambda client: [Enc()])
    monkeypatch.setattr("paf.wcl.WCLClient", lambda: None)
    web.write_assigns(7, "mythic", ["Guillotine@1", "Guillotine@3", "Eternal Nightfall"])
    plan = (tmp_path / "fights" / "boss-mythic.plan.txt").read_text()
    assert "assign Guillotine @1,3\n" in plan and "assign Eternal Nightfall\n" in plan
