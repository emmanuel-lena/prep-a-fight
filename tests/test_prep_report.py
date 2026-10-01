from paf.prep_report import PrepData, headline, render


def test_headline_speaks_the_players_language():
    from paf.fight import AddWave, Fight, Vulnerable
    from paf.optimize import Plan, Rule

    d = PrepData("Ula'tek", "heroic", "Elemental", "Char")
    d.fight = Fight("U", 600, add_waves=[AddWave(60, 5, 20)],
                    vulnerable=[Vulnerable(120, 40, 2.0, "Venomous Heart (after Mother's Wrath)")])
    d.cd_names = {"use_item:trinket1": "Vile Vial", "ascendance": "Ascendance"}

    def rule(name):
        return Rule(name, "", lambda old: old)

    p = Plan("boss", {"ascendance": rule("hold_vulnerable_60"), "use_item:trinket1": rule("hold_vulnerable_60"),
                      "stormkeeper": rule("add_waves")}, 10.3, 0.1)
    p.totals = {"boss": 10.3, "total": 6.8}
    d.optimized = [p]
    text = "\n".join(headline(d))
    assert "Boss damage: +10.3%" in text and "pad +6.8%" in text
    assert "Ascendance, Vile Vial: keep for Venomous Heart if it comes within 60 s" in text
    assert "Stormkeeper: only on add waves" in text
    assert "trinket1" not in text and "secondary" not in text and "hold vulnerable" not in text


def test_raid_section_and_headline():
    from paf.prep_report import RaidInfo
    from paf.raidneed import AOE, AddType, verdicts

    t = AddType("Amani", 100, 18.0, 0.15, {"Balance Druid": 0.44}, 0.25, tops_rate=1000.0, tops_low=900.0)
    vs = verdicts([t], [("Balance Druid", 2500.0)], ("Elemental Shaman", 1000.0))
    d = PrepData("Boss", "mythic", "Elemental", "Char")
    d.raid = RaidInfo("ZJRNbP1DCqQ3grcV", "this boss, kill of 7:28", 20, ("Elemental Shaman", 190e3), False, vs,
                      "boss", [], {AOE: ["Nizae (Balance Druid)"]}, "AoE / funnel")
    assert headline(d)[0].startswith("With your raid: stay on the boss.")
    page = render(d)
    assert "Your raid and the adds" in page and "Nizae (Balance Druid)" in page and "you are not in that log" in page


def test_render_prep_sheet_with_wowhead_links():
    d = PrepData("Boss <X>", "heroic", "Elemental", "Char", kills=10, duration=300)
    d.gear = [("shoulder: Hissing Mantle (321)", {"boss fight": 1.0}, 1.0)]
    d.gear_fights = ["boss fight"]
    d.loot = [("Soul Fang", "main_hand", 0.5, 0.8)]
    d.links = {"Hissing Mantle": "item=271481&ilvl=321", "Soul Fang": "item=271092&ilvl=321"}
    page = render(d)
    assert "{" not in page.split("<main>", 1)[1]  # no unformatted template left
    assert "Boss &lt;X&gt;" in page and "Best gear from your bags" in page
    assert 'data-wowhead="item=271481&amp;ilvl=321"' in page and 'href="https://www.wowhead.com/item=271092"' in page
    assert "wow.zamimg.com/js/tooltips.js" in page
