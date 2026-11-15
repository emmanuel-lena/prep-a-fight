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
    assert defensives.nsrt_lines(d, 3470, phases, "Zapper") == ["time:137.0;ph:1;tag:Zapper;spellid:31224;dur:5"]
    p = PrepData(boss="B", difficulty="mythic", spec="Assassination", character="X")
    p.defensives = d
    html = defensives_html(p)
    assert "Defensives" in html and "2:17" in html and "Soul Transfer" in html and "74% of the kills" in html
    assert "title=" not in html.split("<table>", 1)[1].split("</tr>", 1)[0]  # the method shown, not on a header
    assert "A defensive answers a boss cast within about 10 s" in html and "class='pill" not in html
    p.defensives = Defensives([], [("Astral Shift", 108271, 1.1, 0.64)], 199)
    assert "do not press their defensives at one shared moment" in defensives_html(p)


def test_defensives_are_grouped_by_the_boss_ability_they_answer():
    feast = [DefensiveMoment(t, s, [("Feint", 1966, 0.9), ("Crimson Vial", 185311, 0.1)], "Ravenous Feast", 9)
             for t, s in ((63.0, 0.45), (124.0, 0.51), (219.0, 0.59))]
    loose = [DefensiveMoment(t, 0.3, [("Feint", 1966, 0.8)], "", 0) for t in (170.0, 234.0)]
    p = PrepData(boss="B", difficulty="mythic", spec="Subtlety", character="X")
    p.defensives = Defensives(feast + loose, [], 187)
    p.boss_casts = [("Envenomed", [164.0, 225.0]), ("Ravenous Feast", [61.0, 122.0, 216.0, 371.0])]
    html = defensives_html(p)
    assert html.count("<tr>") == 3  # the header, Ravenous Feast, the untied ones
    # the boss's casts at the fight tab's times, not the top players' median presses (a review: 1:03 here, 1:01
    # there); the untied ones are presses, said so
    assert "&times;3" in html and "1:01, 2:02, 3:36" in html and "45%&ndash;59%" in html
    assert "pressed at 2:50, 3:54" in html and ">Cast at</th>" in html
    assert "None tied in the logs</span> <span class='muted'>&times;2</span>" in html and "Envenomed starts" in html


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


def test_a_defensive_is_never_moved_after_the_top_players_press():
    # Subtlety Rogue, Vashnik (DPS round 10): Feint at 3:05 (6 s) moved to 3:11 for Imbibe "cast" at 3:12, the end
    # of its channel: past the buff
    from paf import fightview

    p = PrepData(boss="Vashnik", difficulty="heroic", spec="Subtlety", character="X")
    p.defensives = Defensives([DefensiveMoment(185.0, 0.41, [("Feint", 1966, 0.81)], "Imbibe", 1)], [], 100)
    p.boss_casts = [("Imbibe", [24.0, 108.0, 192.0])]
    assert [round(t) for t, _s, _w in fightview._defensives(p)] == [185]
    p.boss_casts = [("Imbibe", [24.0, 108.0, 184.0])]  # a cast just before: the press goes just before it
    assert [round(t) for t, _s, _w in fightview._defensives(p)] == [183]
