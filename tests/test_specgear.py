from paf import specgear, workshop, workshop_views
from paf.specgear import MyKills, Result, SpecRow


def item(i, **kw):
    return {"id": i, "name": f"Item {i}", "itemLevel": "331", **kw}


def player(**slots):
    gear = [{} for _ in range(17)]
    for slot, it in slots.items():
        gear[int(slot[1:])] = it
    return {"gear": gear}


def test_the_set_is_what_the_tops_wear_most_slot_by_slot():
    rows = [
        player(s0=item(1, permanentEnchant="7"), s10=item(20), s11=item(21), s12=item(30), s13=item(31),
               s15=item(50)),  # a two-hander
        player(s0=item(1), s10=item(21), s11=item(22), s12=item(31), s13=item(32), s15=item(60), s16=item(61)),
        player(s0=item(2), s10=item(22), s11=item(21), s12=item(31), s13=item(30), s15=item(60), s16=item(62)),
        player(s15=item(60), s16=item(61)),
    ]
    gear = specgear.common_set(rows)
    assert gear[0]["id"] == 1 and gear[0]["permanentEnchant"] == "7"  # enchant of the best ranked who wears it
    assert {gear[10]["id"], gear[11]["id"]} == {21, 22}  # the two most worn rings, whatever their slot
    assert {gear[12]["id"], gear[13]["id"]} == {31, 30}
    assert gear[15]["id"] == 60 and gear[16]["id"] == 61  # the off-hand worn with that main hand, no two-hander mix


def test_every_item_goes_to_the_top_item_level_with_its_bonuses():
    gear = [{} for _ in range(17)]
    gear[0] = item(271483, bonusIDs=["6652", "13335"], gems=[{"id": "240983"}], permanentEnchant="8017")
    gear[3] = item(5)  # the shirt is not simmed
    lines = specgear.gear_lines(gear)
    assert lines == ["head=,id=271483,bonus_id=6652/13335,enchant_id=8017,gem_id=240983,ilevel=334"]


def test_your_character_in_another_spec_keeps_who_you_are():
    profile = ('# a comment\nshaman="Zapper"\nlevel=90\nrace=orc\nregion=eu\nserver=hyjal\nrole=spell\n'
               'professions=alchemy=100\nspec=elemental\ntalents=OLD\nhead=,id=1\n')
    gear = [{} for _ in range(17)]
    gear[15] = item(9)
    text = specgear.character_in(profile, "Enhancement", ["talents=NEW"], gear)
    assert text.startswith('shaman="Zapper"\nlevel=90\nrace=orc\nregion=eu\nserver=hyjal\nprofessions=alchemy=100\n')
    assert "spec=enhancement\ntalents=NEW\nmain_hand=,id=9,ilevel=334" in text
    assert "id=1" not in text and "OLD" not in text and "role=" not in text
    assert specgear.simc_spec("BeastMastery") == "beast_mastery"
    assert specgear.spec_label("BeastMastery") == "Beast Mastery"


def result(mine_sim, other_sim, mine_tops=100.0, other_tops=100.0, error=0.1):
    return Result("Boss", "heroic", "Elemental", [
        SpecRow("Elemental", mine_tops, 95, 105, mine_sim, error), SpecRow("Enhancement", other_tops, 95, 105,
                                                                           other_sim, error)], now=90.0)


def test_the_verdict_says_play_stay_or_that_the_sim_and_the_logs_disagree():
    kind, text = specgear.verdict(result(100.0, 106.0, other_tops=104.0))
    assert kind == "go" and text.startswith("Enhancement could do more here: ") and "+6.0%" in text and "+4%" in text
    kind, text = specgear.verdict(result(100.0, 100.2))
    assert kind == "ok" and text.startswith("Elemental fits this boss: ") and "within the noise" in text
    kind, text = specgear.verdict(result(100.0, 95.0))
    assert kind == "ok" and "it sims 5.0% over Enhancement" in text
    kind, text = specgear.verdict(result(100.0, 106.0, other_tops=97.0))
    assert kind == "warn" and "disagree" in text and "Elemental is the safer choice" in text


def test_the_gear_and_your_kills_in_a_sentence():
    r = result(100.0, 95.0)
    assert specgear.gear_sentence(r).startswith("The top players' gear at 334 is worth +11.1% to your Elemental")
    assert specgear.kills_sentence(r).startswith("No ranked kill of yours on Boss heroic in Elemental yet")
    r.kills = MyKills("Elemental", [80.0, 90.0, 85.0])
    assert specgear.kills_sentence(r) == ("Your 3 ranked kills here: best 90, median 85 DPS of boss damage, 100% of "
                                          "your sim as you are (90); the top Elemental players 100.")


def test_your_kills_come_from_your_rankings_in_your_spec():
    asked = {}

    class Client:
        def query(self, q, v, cache_ttl=None):
            asked.update(v)
            return {"characterData": {"character": {"encounterRankings": {"ranks": [
                {"amount": 120.0, "spec": "Elemental"}, {"amount": 200.0, "spec": "Enhancement"},
                {"amount": 140.0, "spec": "Elemental"}]}}}}

    k = specgear.my_kills(Client(), "Zapper", "Twisting Nether", "eu", 3492, 4, "Elemental")
    assert k.amounts == [120.0, 140.0] and k.best == 140.0
    assert asked["s"] == "twisting-nether" and asked["r"] == "EU" and asked["m"] == "bossdps"
    assert specgear.my_kills(Client(), "", "x", "eu", 1, 4, "Elemental") is None


def test_the_tops_median_comes_with_its_noise():
    t = specgear.Tops("Elemental", [float(x) for x in range(100, 200)])
    lo, hi = t.interval()
    assert lo < t.median < hi and hi - lo < 20


def test_the_result_page_and_the_tool():
    r = result(100.0, 106.0, other_tops=104.0)
    html = workshop_views.render({"kind": "specgear", **specgear.to_json(r)})
    assert "Enhancement could do more here" in html and "Each spec on you" in html
    assert "the best of three builds" in html
    assert "specgear" in workshop.BY_CMD
    args = workshop.args("specgear", {"boss": ["3492"], "difficulty": ["heroic"]})
    assert args[:2] == ["specgear", "3492"] and "--difficulty" in args


def test_a_spec_without_enough_tops_is_left_out():
    class Client:
        def query(self, q, v, cache_ttl=None):
            return {"worldData": {"encounter": {"characterRankings": {"rankings": [{"amount": 1, "gear": []}] * 3}}}}

    assert specgear.tops(Client(), 1, 4, "Shaman", "Enhancement") is None


def test_the_build_is_the_one_most_top_players_play():
    a = [{"talentID": 1, "points": 1}, {"talentID": 2, "points": 2}]
    b = [{"talentID": 1, "points": 1}, {"talentID": 3, "points": 1}]
    rows = [{"talents": b}, {"talents": list(reversed(a))}, {"talents": a}, {"talents": []}]
    assert specgear.common_build(rows) == ((1, 1), (2, 2))
    assert specgear.common_build([{"talents": []}]) == ()
