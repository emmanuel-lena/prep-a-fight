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
