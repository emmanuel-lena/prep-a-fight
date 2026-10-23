import pytest

from paf import raidlead, talents


@pytest.fixture(autouse=True)
def _no_game_data(monkeypatch):  # which talents are buttons the rotation never presses: from simc and the game data
    monkeypatch.setattr(talents, "utility", lambda names, cls, spec: set())

NAMES = {1: "Malefic Grasp", 2: "Seed of Corruption", 3: "Sow the Seeds", 4: "Haunt"}
STATE = {
    "players": [["Nolow", "Affliction Warlock", 900_000], ["Frosty", "Frost Mage", 950_000]],
    "talents": {"Nolow": [2, 3, 4], "Frosty": [1]},
    # talent -> (share of the top 100 by total DPS, share of the top 100 by boss DPS)
    "splits": {"7|4|Affliction Warlock": {"1": [0.1, 0.8], "2": [0.9, 0.2], "3": [0.7, 0.3], "4": [0.9, 0.9]}},
}


def test_a_player_on_the_boss_drops_the_padding_talents():
    out = raidlead.builds(STATE, 7, 4, {}, NAMES)
    assert out == [{"name": "Nolow", "spec": "Affliction Warlock", "side": "boss", "take": ["Malefic Grasp"],
                    "drop": ["Seed of Corruption", "Sow the Seeds"], "more": 0, "choice": []}]


def test_a_button_the_rotation_never_presses_is_the_players_choice(monkeypatch):
    monkeypatch.setattr(talents, "utility", lambda names, cls, spec: {"Sow the Seeds"} & set(names))
    out = raidlead.builds(STATE, 7, 4, {}, NAMES)
    assert out[0]["drop"] == ["Seed of Corruption"] and out[0]["choice"] == ["Sow the Seeds"]
    # a player whose only gap is such a button is on their build
    only = {**STATE, "talents": {"Nolow": [1, 3, 4]}}
    monkeypatch.setattr(talents, "utility", lambda names, cls, spec: set(names))
    assert raidlead.builds(only, 7, 4, {}, NAMES) == []


def test_a_player_on_an_add_keeps_the_padding_talents():
    assert raidlead.builds(STATE, 7, 4, {"Nolow": "pad"}, NAMES) == []  # already a padding build


def test_the_text_for_discord_and_mrt():
    sh = {"boss": "Nek'zali", "targets": [
        {"name": "Drowned Add", "whole_raid": False, "second_boss": False, "players": ["Rogue", "Hunter"], "best": []},
        {"name": "Tentacle", "whole_raid": True, "second_boss": False, "players": [], "best": []}],
        "builds": [{"name": "Nolow", "spec": "Affliction Warlock", "side": "boss", "take": ["Malefic Grasp"],
                    "drop": ["Seed of Corruption"]}]}
    discord = raidlead.text(sh, "heroic")
    assert discord.splitlines() == [
        "**Nek'zali (heroic)**", "Drowned Add: Rogue, Hunter", "Tentacle: everyone",
        "Nolow (boss talents): take Malefic Grasp / drop Seed of Corruption"]
    assert raidlead.text(sh, "heroic", mrt=True).startswith("Nek'zali (heroic)\n")
    empty = {"boss": "Ula'tek", "targets": [], "builds": []}
    assert raidlead.text(empty, "mythic").endswith("Everyone on the boss, no change.")


def test_bench(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    raidlead.save({"players": STATE["players"]})
    raidlead.toggle_bench("Nolow")
    assert raidlead.load()["bench"] == ["Nolow"]
    raidlead.toggle_bench("Nolow")
    assert raidlead.load()["bench"] == []


def test_the_page_opens_on_the_answer(tmp_path, monkeypatch):
    """Nek'zali heroic, a real roster (2026-10-20): the page opens on what is ready to copy, never on "everyone stays on
    the boss" while three players are named on the Restless Amani (an add the whole raid may also hit)."""
    from types import SimpleNamespace

    from paf import web

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    more = [["Ssamii", "Balance Druid", 1], ["Tristy", "Beast Mastery Hunter", 1]]
    raidlead.save({"players": STATE["players"] + more, "report": "abcd", "roster_from": "another boss, pull of 3:10"})
    monkeypatch.setattr(web, "_encounters", lambda: [SimpleNamespace(id=3470, name="Nek'zali the Soulcoiler")])
    monkeypatch.setattr(web, "journal_order", lambda encs: encs)
    sh = {"boss": "Nek'zali", "targets": [
        {"name": "Restless Amani", "whole_raid": True, "second_boss": False, "players": ["Frosty", "Ssamii", "Tristy"],
         "best": ["Frost Mage"]},
        {"name": "Echo of Jawae", "whole_raid": True, "second_boss": False, "players": [], "best": []}],
        "builds": [{"name": "Ssamii", "spec": "Balance Druid", "side": "pad", "take": ["A"], "drop": []},
                   {"name": "Nolow", "spec": "Affliction Warlock", "side": "boss", "take": ["B"], "drop": []}]}
    monkeypatch.setattr(raidlead, "sheet", lambda state, x, diff: sh)
    monkeypatch.setattr(raidlead, "lust_block", lambda sh, difficulty: "")
    page = raidlead.page_body("heroic")
    assert "1 boss to copy for Discord, for the 4 players of your raid.</p>" in page
    assert "everyone stays on the boss" not in page and "Frosty, Ssamii, Tristy" in page


def test_a_few_swaps_stay_chips_another_build_is_one_badge():
    # app round 11: Ssamii 8 talents apart read "another build: play the top players' pad build"
    few = {"name": "Ssamii", "spec": "Balance Druid", "side": "pad", "take": [f"T{i}" for i in range(4)],
           "drop": [f"D{i}" for i in range(4)], "more": 0}
    many = dict(few, name="Hilander", take=[f"T{i}" for i in range(20)], drop=[f"D{i}" for i in range(18)])
    sh = {"boss": "Nek'zali", "targets": [], "builds": [few, many]}
    lines = raidlead.text(sh, "heroic").splitlines()
    assert lines[1].startswith("Ssamii (padding talents): take T0") and "another build (38 talents apart)" in lines[2]


def test_the_strip_says_what_each_boss_asks():
    # fresh app reviews 1-3: nine boss cards of the same weight, no overview at the top
    from types import SimpleNamespace

    x = SimpleNamespace(id=7, name="Vashnik")
    sh = {"targets": [{"players": ["A", "B"]}, {"players": []}], "builds": [{}, {}, {}]}
    cell = raidlead._strip_cell(x, sh)
    assert "href='#boss-7'" in cell and "2 on adds" in cell and "3 players to change talents" in cell
    assert "nothing to change" in raidlead._strip_cell(x, {"targets": [], "builds": []})
    assert "no kills read" in raidlead._strip_cell(x, None)
    # no spec with a pad/boss build on this boss (Coiled Altar): nothing compared, never "nothing to change"
    none = raidlead._strip_cell(x, {"targets": [], "builds": [], "no_split": 18}, 18)
    assert "no pad/boss build" in none and "nothing to change" not in none
