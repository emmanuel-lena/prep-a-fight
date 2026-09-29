import pytest

from paf.fight import AddWave, Fight, Vulnerable
from paf.notes import apply_notes, notes_template, parse_notes


def fight():
    return Fight("B", 300, add_waves=[AddWave(20, 5, 15, "Rawling"), AddWave(5, 1, 290, "Gore Rattle", scalable=False)],
                 vulnerable=[Vulnerable(120, 44, 2.64, "Venomous Heart (after Serpent's Bite)"),
                             Vulnerable(270, 44, 2.64, "Venomous Heart")])


def test_parse_notes():
    n = parse_notes("﻿# c\namp Venomous Heart 2.0\nignore Gore Rattle\nseparate Shield\n")
    assert n.amp == {"venomous heart": 2.0} and n.ignore == {"gore rattle"} and n.separate == {"shield"}
    with pytest.raises(ValueError, match="line 1"):
        parse_notes("amp Heart lots\n")


def test_apply_notes_amp_ignore_separate():
    f, changes = apply_notes(fight(), parse_notes("amp Venomous Heart 2\nignore Gore Rattle\n"))
    assert [v.multiplier for v in f.vulnerable] == [2.0, 2.0]
    assert [w.name for w in f.add_waves] == ["Rawling"]
    assert len(changes) == 3
    g, _ = apply_notes(fight(), parse_notes("separate Venomous Heart\n"))
    assert not g.vulnerable and [w.name for w in g.add_waves if not w.scalable].count("Venomous Heart") == 1


def test_refresh_notes_keeps_player_lines(tmp_path):
    from paf.notes import notes_path, refresh_notes

    fj = tmp_path / "boss-heroic.json"
    notes_path(fj).write_text("# old detected stuff\namp Venomous Heart 2\n")
    text = refresh_notes(fj, fight()).read_text()
    assert "# amp Venomous Heart 2.64" in text and "\namp Venomous Heart 2\n" in text
    assert parse_notes(text).amp == {"venomous heart": 2.0}


def test_notes_template_lists_detected_units_once():
    text = notes_template(fight())
    assert text.count("# amp Venomous Heart 2.64") == 1
    assert parse_notes(text).empty  # everything is commented out
