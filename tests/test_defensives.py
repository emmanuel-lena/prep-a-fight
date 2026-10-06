from paf import defensives, pack
from paf.defensives import DefensiveMoment, Defensives, peaks
from paf.prep_report import PrepData, defensives_html


def test_peaks_find_the_shared_moments():
    per_kill = [[60, 200], [62], [58, 300], [120], []]  # 3 of 5 kills press one around 1:00
    assert peaks(per_kill, window=8, support=0.25) == [60]
    assert peaks(per_kill, window=8, support=0.7) == []


def _defs() -> Defensives:
    return Defensives([DefensiveMoment(137.0, 0.33, [("Cloak of Shadows", 31224, 0.66), ("Feint", 1966, 0.37)],
                                       "Soul Transfer", 1234)], [("Feint", 1966, 2.5, 0.74)], 199)


def test_notes_and_sheet():
    d = _defs()
    assert defensives.mrt_lines(d) == ["{time:2:17} Defensive: Cloak of Shadows / Feint - Soul Transfer"]
    phases = [("Stage One", 0.0), ("Intermission", 158.0)]
    assert defensives.nsrt_lines(d, 3470, phases, "Ixuu") == ["time:137.0;ph:1;tag:Ixuu;spellid:31224;dur:5"]
    p = PrepData(boss="B", difficulty="mythic", spec="Assassination", character="X")
    p.defensives = d
    html = defensives_html(p)
    assert "Defensives" in html and "2:17" in html and "Soul Transfer" in html and "74% of the kills" in html
    p.defensives = Defensives([], [("Astral Shift", 108271, 1.1, 0.64)], 199)
    assert "do not press their defensives at one shared moment" in defensives_html(p)


def test_defensives_travel_in_the_pack(tmp_path, monkeypatch):
    from tests.test_pack import _pack

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    p = _pack()
    p.defensives = _defs()
    q = pack.from_json(pack.to_json(p))
    assert q.defensives.moments[0].spells[0] == ("Cloak of Shadows", 31224, 0.66)
    assert q.defensives.usage[0] == ("Feint", 1966, 2.5, 0.74) and q.defensives.kills == 199
    p.defensives = None  # packs made before defensives
    assert pack.from_json(pack.to_json(p)).defensives is None
