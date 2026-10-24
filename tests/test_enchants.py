from paf import enchants, workshop_views


def row(chest_enchant, gems):
    gear = [{} for _ in range(17)]
    gear[4] = {"id": 100, "permanentEnchant": chest_enchant}
    gear[0] = {"id": 101, "gems": [{"id": g} for g in gems]}
    return {"amount": 1, "gear": gear}


ROWS = [row(7001, [5000, 6001, 6001])] * 6 + [row(7002, [5000, 6002, 6002])] * 3 + [row(7003, [5000, 6001, 6001])]


def test_the_candidates_are_what_the_top_players_wear():
    # the Gear tool (the owner, 2026-10-24): never a fixed list, the season's from the rankings
    assert enchants.unique_gems(ROWS) == {5000}  # worn once by every player: a unique gem, never everywhere
    got = {(c.kind, c.slot, c.item): round(c.share, 2) for c in enchants.candidates(ROWS)}
    assert got[("enchant", "chest", 7001)] == 0.6 and got[("enchant", "chest", 7003)] == 0.1
    assert got[("gem", "", 6001)] == 0.7 and ("gem", "", 5000) not in got


PROFILE = """rogue="T"
head=,id=101,gem_id=5000/6002
chest=,id=100,enchant_id=7002
chest=,id=200,enchant_id=7002
"""


def test_an_enchant_goes_on_the_set_top_gear_chose_and_a_gem_leaves_the_unique_one():
    picks = [enchants.Choice("enchant", "chest", 7001, 0.6), enchants.Choice("gem", "", 6001, 0.7)]
    sets = enchants.variants(PROFILE, picks, {5000})
    assert sets["e0"] == ["chest=,id=200,enchant_id=7001"]  # the last chest line: the set Top Gear put on
    assert sets["g1"] == ["head=,id=101,gem_id=5000/6001"]
    out = enchants.apply(PROFILE, picks, {5000})
    assert "chest=,id=200,enchant_id=7001" in out and "head=,id=101,gem_id=5000/6001" in out
    assert out.count("chest=") == 2  # changed in place, no line added


def test_the_gear_page_says_what_to_change():
    page = workshop_views.render({"kind": "gear", "fights": [], "enchants": {"error": 0.1, "rows": [
        {"kind": "enchant", "slot": "chest", "name": "Crystalline Radiance", "id": 7001, "share": 0.6, "gain": 0.8,
         "pick": True},
        {"kind": "gem", "slot": "", "name": "Deadly Garnet", "id": 6001, "share": 0.7, "gain": 0, "pick": False}]}})
    assert "<b>&#10003; change</b>" in page and "Crystalline Radiance" in page and "+0.80%" in page
    assert "every socket" in page and ">worn<" in page


def test_a_game_string_reads_as_a_player_reads_it():
    assert enchants.readable("Enchant Helm - Rune |A:Professions-ChatIcon-Quality-12-Tier2:20:20|a") == \
        "Enchant Helm - Rune (rank 2)"
    assert enchants.readable("|cnIQ4:Ancient Hash'ey Battle Art: Heat Wave|r") == \
        "Ancient Hash'ey Battle Art: Heat Wave"
    assert enchants.readable("+$k2 Agility/Strength & +$k1 Stamina") == "+Agility/Strength & +Stamina"
