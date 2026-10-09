from paf import raidlead

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
                    "drop": ["Seed of Corruption", "Sow the Seeds"]}]


def test_a_player_on_an_add_keeps_the_padding_talents():
    assert raidlead.builds(STATE, 7, 4, {"Nolow": "pad"}, NAMES) == []  # already a padding build


def test_the_text_for_discord_and_mrt():
    sh = {"boss": "Nek'zali", "targets": [
        {"name": "Drowned Add", "whole_raid": False, "second_boss": False, "players": ["Rogue", "Hunter"], "best": []},
        {"name": "Tentacle", "whole_raid": True, "second_boss": False, "players": [], "best": []}],
        "builds": [{"name": "Nolow", "spec": "Affliction Warlock", "side": "boss", "take": ["Malefic Grasp"],
                    "drop": ["Seed of Corruption"]}],
        "swaps": [{"name": "Dk", "current": "Unholy Death Knight", "better": "Frost Death Knight", "gain": 0.06}]}
    discord = raidlead.text(sh, "heroic")
    assert discord.splitlines() == [
        "**Nek'zali (heroic)**", "Drowned Add: Rogue, Hunter", "Tentacle: everyone",
        "Nolow (boss talents): take Malefic Grasp / drop Seed of Corruption",
        "Dk: Frost Death Knight does +6% boss damage vs Unholy Death Knight"]
    assert raidlead.text(sh, "heroic", mrt=True).startswith("Nek'zali (heroic)\n")
    empty = {"boss": "Ula'tek", "targets": [], "builds": [], "swaps": []}
    assert raidlead.text(empty, "mythic").endswith("Everyone on the boss, no change.")


def test_bench(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    raidlead.save({"players": STATE["players"]})
    raidlead.toggle_bench("Nolow")
    assert raidlead.load()["bench"] == ["Nolow"]
    raidlead.toggle_bench("Nolow")
    assert raidlead.load()["bench"] == []
