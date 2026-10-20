"""Reclear (issue #24): a pull's points priced, the costly first, with the top players and the log's moment."""
from paf import lastraid, rotation
from paf.rotation import Cast, CooldownFinding, Log, Review


def _log():
    casts = [Cast(t, 1, None) for t in range(0, 60, 1)] + [Cast(t, 1, None) for t in range(100, 180, 1)]
    casts += [Cast(5.0, 114050, None)]  # Ascendance once
    return Log(180.0, sorted(casts, key=lambda c: c.t), [], {1: "Lightning Bolt", 114050: "Ascendance"})


def test_a_cooldown_left_ready_is_found_with_where():
    f = CooldownFinding("Ascendance", 60.0, 1, 1, 3, [5.0])
    assert rotation.idle_windows(f, 180.0)[0] == (65.0, 115.0)  # ready from 1:05 to the end


def test_the_costly_points_come_first():
    log = _log()
    r = Review("Me", "Elemental Shaman", "pull 3", 180.0,
               cooldowns=[CooldownFinding("Ascendance", 60.0, 1, 1, 3, [5.0])])
    found = rotation.findings(r, log, tops_busy=0.95, tops_casts={"ascendance": 1.0},
                              values={"Ascendance": (2.5, 0.2)})
    assert [round(f.cost, 1) for f in found[:2]] == [18.1, 5.0]  # 140 s of 180 cast: 78% against 95%; 2 x 2.5%
    asc = found[1]
    assert asc.text == "Ascendance: you pressed it 1 time; 3 fit in this pull (held 115 s from 1:05)."
    f = CooldownFinding("Stormkeeper", 30.0, 1, 6, 7, [5.0, 35.0, 65.0, 95.0, 125.0, 170.0])
    same = rotation.findings(Review("Me", "x", "p", 180.0, cooldowns=[f]), log, None, {"stormkeeper": 1.7},
                             {"Stormkeeper": (3.3, 0.1)})[0]
    assert same.text.startswith("Stormkeeper: you pressed it 6 times; 7 fit in this pull")
    assert asc.tops == "the top players of your spec press it 3.0 times in a pull this long" and asc.at == 65.0
    assert asc.noise == 0.4
    link = rotation.log_link("abcd", {"id": 3, "startTime": 1000, "endTime": 181_000}, 7, asc.at)
    assert link.endswith("#fight=3&type=casts&source=7&start=61000&end=91000")


def test_reclear_shows_the_price_the_tops_and_the_moment():
    html = lastraid._li({"text": "Ascendance: pressed 1 of 3 times it was ready.", "cost": "&minus;5.0%",
                         "tops": "the top players of your spec press it 3.0 times a kill", "link": "https://x"})
    assert "&minus;5.0%</b><span>Ascendance" in html and ">Open the pull on Warcraft Logs" in html
    assert lastraid._key({"text": "Ascendance: pressed"}) == "ascendance"
