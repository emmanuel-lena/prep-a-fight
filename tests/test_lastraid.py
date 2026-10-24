from dataclasses import dataclass

import pytest

from paf import lastraid


@dataclass
class Enc:
    id: int
    name: str


ENCS = [Enc(1, "Ula'tek"), Enc(2, "Nek'zali"), Enc(3, "The Lost Explorers")]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    return tmp_path


def test_the_bosses_of_a_log_not_killed_first():
    fights = [{"encounterID": 1, "difficulty": 4, "kill": True, "bossPercentage": 0},
              {"encounterID": 2, "difficulty": 4, "kill": False, "bossPercentage": 42.5},
              {"encounterID": 2, "difficulty": 4, "kill": False, "bossPercentage": 18.0},
              {"encounterID": 99, "difficulty": 4, "kill": True},  # an older raid's boss
              {"encounterID": 3, "difficulty": 1, "kill": True}]  # LFR
    bosses = lastraid.bosses_of(fights, ENCS)
    assert [(b["name"], b["kill"], b["pulls"]) for b in bosses] == [("Nek'zali", False, 2), ("Ula'tek", True, 1)]
    assert bosses[0]["best"] == 18.0 and bosses[0]["difficulty"] == "heroic"


def test_a_killed_boss_gets_the_rotation_review_a_wipe_why_and_the_pulls():
    kill = {"boss": 1, "difficulty": "heroic", "kill": True}
    wipe = {"boss": 2, "difficulty": "mythic", "kill": False}
    assert [k for k, _ in lastraid._tools(kill, "abc", "Me")] == ["rotation"]
    tools = dict(lastraid._tools(wipe, "abc", "Me"))
    assert set(tools) == {"wipe", "diff"} and tools["diff"][-2:] == ["--player", "Me"]
    assert "https://www.warcraftlogs.com/reports/abc" in tools["wipe"]


def test_the_ticked_characters(home, monkeypatch):
    monkeypatch.setattr("paf.characters.current_slug", lambda: "me-shaman")
    assert lastraid.ticked() == {"me-shaman"}  # by default, the active one
    lastraid.tick("alt-priest", True)
    assert lastraid.ticked() == {"me-shaman", "alt-priest"}
    lastraid.tick("me-shaman", False)
    assert lastraid.ticked() == {"alt-priest"}


def test_what_to_clean_from_the_results(monkeypatch):
    results = {
        "w": {"left": 0.12, "longest_kill": 470.0, "kill": {"no_deaths": 455.0},
              "culprits": [{"name": "Me", "lost_alive": 0.02, "lost_dead": 0.015, "pad_talents": ["Chain Reaction"]}]},
        "d": {"highlights": [{"kind": "good", "text": "B lost 3 fewer players."}]},
        "r": {"highlights": ["Flame Shock refreshed early 40% of the time."]},
    }
    monkeypatch.setattr(lastraid, "_result", lambda jid: results.get(jid))
    wiped = lastraid.sentences({"kill": False, "jobs": {"wipe": "w", "diff": "d"}}, "me")
    assert wiped[0].startswith("Your best pull left the boss at 12%: without the deaths it dies at 7:35")
    assert "3.5% of the boss's health lost, 1.5% while dead; padding talents: Chain Reaction" in wiped[1]
    assert wiped[2] == "B lost 3 fewer players."
    assert lastraid.sentences({"kill": True, "jobs": {"rotation": "r"}}, "me") == [
        "Flame Shock refreshed early 40% of the time."]


def test_a_point_on_most_bosses_is_said_once():
    rite = "Halazzi's Rite: you never had it; the top players of your spec keep it up 58% of the fight."
    grace = "Spiritwalker's Grace: you pressed it 1 time, it was ready 2 times in the pull."
    per_boss = [[rite, grace], [rite], [rite, "Cleave: Chain Lightning low."]]
    assert lastraid.common(per_boss) == [
        "Halazzi's Rite: you never had it; the top players of your spec keep it up 58% of the fight (on 3 bosses)."]
    assert lastraid.common(per_boss[:2]) == []


def test_the_home_card(home, monkeypatch):
    monkeypatch.setattr(lastraid, "_result", lambda jid: {"highlights": ["Keep Ascendance for the adds."]})
    lastraid.save({"me": {"report": "abc", "player": "Me", "date": 1791500000, "pulls": 12, "night": "n1",
                          "finished": 1791500100, "bosses": [
                              {"boss": 1, "name": "Ula'tek", "difficulty": "heroic", "kill": True, "pulls": 3,
                               "best": 0.0, "jobs": {"rotation": "r1"}}]}})
    html = lastraid.card("me")
    assert "Your last raid" in html and "killed in 3 pulls" in html and "Keep Ascendance for the adds." in html
    assert "/job/r1" in html and "/job/n1" in html and "Read the last log again" in html
    assert lastraid.card("nobody") == ""


def test_a_log_without_a_boss_of_the_raid_is_skipped(home, monkeypatch):
    from paf import jobrun, tracker

    logs = {"dungeon": [{"encounterID": 99, "difficulty": 10, "kill": True}],
            "raid": [{"encounterID": 1, "difficulty": 4, "kill": True}]}

    class Client:
        def query(self, q, v, cache_ttl=None):
            return {"reportData": {"report": {"startTime": 0, "fights": logs[v["c"]]}}}

    monkeypatch.setattr(lastraid, "who", lambda slug: ("Me", "Draenor", "eu"))
    monkeypatch.setattr(tracker, "character_reports", lambda *a: ["dungeon", "raid"])
    monkeypatch.setattr(jobrun, "run_job", lambda args, log=None: ("j1", "done"))
    state = {}
    assert lastraid.read_one(Client(), "me-shaman", state, ENCS, log=lambda *a: None)
    assert state["me-shaman"]["report"] == "raid" and state["me-shaman"]["bosses"][0]["name"] == "Ula'tek"


def test_a_boss_in_two_difficulties_keeps_its_own_review(home, monkeypatch):
    monkeypatch.setattr(lastraid, "_result", lambda jid: {"highlights": [f"Review {jid}."]})
    bosses = [{"boss": 2, "name": "Nek'zali", "difficulty": d, "pulls": 1, "kill": True, "best": 0.0,
               "jobs": {"rotation": d}} for d in ("heroic", "mythic")]
    lastraid.save({"me": {"report": "abc", "player": "Me", "date": 1791500000, "pulls": 2, "night": "n1",
                          "finished": 1791500100, "bosses": bosses}})
    html = lastraid.card("me")
    assert "Review heroic." in html and "Review mythic." in html


def test_a_pull_comparison_says_best_pull_not_b():
    assert lastraid._ab("Share of the raid's damage on Vashnik: 59% in B, 54% in A.") == (
        "Share of the raid's damage on Vashnik: 59% in your best pull, 54% in your weaker pull.")
    assert lastraid._ab("Ixuu: active 99% of the pull in B, 89% in A.", "Ixuu") == (
        "You: active 99% of the pull in your best pull, 89% in your weaker pull.")


def test_the_headline_of_a_raid(tmp_path, monkeypatch):
    """Ixuu's last raid (2026-10-18): 35 pulls of Sszorak mythic, best at 58%; Home and Reclear say it in one line."""
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setattr(lastraid, "load", lambda: {"ixuu-rogue": {"bosses": [
        {"name": "Sszorak", "difficulty": "mythic", "kill": False, "best": 57.62},
        {"name": "Vashnik the Malignant", "difficulty": "heroic", "kill": True, "best": 0}]}})
    assert lastraid.headline("ixuu-rogue") == (
        "Sszorak mythic, your best pull got it to 58%; Vashnik the Malignant heroic killed.")
    assert lastraid.headline("nobody") == ""


def test_the_pull_comparison_is_a_table(monkeypatch):
    # the owner (less text): "You: 252k on the boss in your best pull, 209k in your weaker pull." three times over
    d = {"highlights": [
        {"kind": "good", "text": "Ixuu: 252k on the boss in B, 209k in A.",
         "row": ["Ixuu: damage on the boss", "252k", "209k"]},
        {"kind": "bad", "text": "At 2:38, the boss had 66% left in B against 69% in A.",
         "row": ["Boss health left at 2:38", "66%", "69%"]}]}
    monkeypatch.setattr(lastraid, "_result", lambda jid: d if jid == "d" else None)
    says = lastraid.sentences({"kill": False, "jobs": {"diff": "d"}}, "Ixuu")
    assert says[0]["cmp"] == ["You: damage on the boss", "252k", "209k"]
    table = lastraid._cmp_table(says)
    assert ("<tr class='good'><td>You: damage on the boss</td><td><b>252k<span class='lr-bar' aria-hidden='true'>"
            "<span style='width:100%'></span></span></b></td><td>209k<span class='lr-bar' aria-hidden='true'>"
            "<span style='width:83%'></span></span></td><td class='gap'>+21%</td></tr>") in table
    assert lastraid._row_of("Ixuu: active 99% of the pull in B, 89% in A.") == ["Ixuu: active time", "99%", "89%"]


def test_the_comparison_headers_keep_the_time_when_the_health_is_a_row():
    # app round 16: "wipe at 66% after 2:38" in the header, "Boss health left at 2:38 | 66%" right below
    rows = [{"cmp": ("Boss health left at 2:38", "66%", "69%"), "kind": "good",
             "pulls": ["wipe at 66% after 2:38", "wipe at 69% after 2:44"]}]
    out = lastraid._cmp_table(rows)
    assert "Best 0-death pull <small>&#9201;&nbsp;2:38</small>" in out and "wipe at 66%" not in out


def test_a_one_boss_wipe_night_has_no_empty_state_line(home, monkeypatch):
    # app confirm round 2: an orange dot alone under the boss name
    monkeypatch.setattr(lastraid, "_result", lambda jid: {})
    lastraid.save({"me": {"report": "abc", "player": "Me", "date": 1791500000, "pulls": 35, "night": "n1",
                          "finished": 1791500100, "bosses": [
                              {"boss": 1, "name": "Sszorak", "difficulty": "mythic", "kill": False, "pulls": 35,
                               "best": 58.0, "jobs": {}}]}})
    assert "lr-state" not in lastraid.card("me")


def test_the_prepare_line_survives_a_full_comparison_table(home, monkeypatch):
    # app confirm round 3: three table rows filled the [:3] cut, the "Prepare … to see why" line was dropped
    rows = [{"row": [f"Row {i}", "1", "2"], "kind": "good", "text": f"Row {i}"} for i in range(3)]
    monkeypatch.setattr(lastraid, "_result", lambda jid: {"highlights": rows} if jid == "d1" else None)
    lastraid.save({"me": {"report": "abc", "player": "Me", "date": 1791500000, "pulls": 35, "night": "n1",
                          "finished": 1791500100, "bosses": [
                              {"boss": 1, "name": "Sszorak", "difficulty": "mythic", "kill": False, "pulls": 35,
                               "best": 58.0, "jobs": {"diff": "d1"}}]}})
    html = lastraid.card("me")
    assert "<nav class='lr-links'><a href='/boss?boss=1&amp;difficulty=mythic'>Sszorak's prep &rarr; why it" in html
    assert "lr-cmp" in html  # the table too
