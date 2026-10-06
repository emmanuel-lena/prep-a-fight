from paf import raidneed, raidplan


def test_what_happened_reads_boss_and_add_damage_from_the_log():
    rc = raidneed.RaidComp("ABC", "this boss, kill of 5:00", [
        ("Ann", "Elemental Shaman", 300e3), ("Bob", "Fire Mage", 200e3), ("Cid", "Holy Priest", 20e3)],
        {"Ann": {"Boss": 30e6, "Add": 60e6}, "Bob": {"Boss": 57e6, "Add": 3e6}, "Cid": {"Boss": 6e6}}, 300.0, True)
    played = raidplan.what_happened(rc, {"Boss"}, {"Elemental Shaman": 0.4, "Fire Mage": 0.1})
    ann = next(x for x in played if x.name == "Ann")
    assert round(ann.boss) == 100_000 and round(ann.adds) == 200_000 and ann.verdict == "padded more than the tops"
    assert next(x for x in played if x.name == "Bob").verdict == "like the top players"
    assert played[-1].name == "Cid"  # healers last
    rc.same_boss = False
    assert raidplan.what_happened(rc, {"Boss"}, {}) == []


def test_raid_page_has_two_sections():
    rc = raidneed.RaidComp("ABC", "kill", [("Ann", "Elemental Shaman", 300e3)], {"Ann": {"Boss": 90e6}}, 300.0, True)
    played = raidplan.what_happened(rc, {"Boss"}, {})
    p = raidplan.Plan([], 300e3, 0.0, 50e3, 300e3, 0.0, False)
    html = raidplan.render(p, "Boss", "mythic", "ABC", "kill", played)
    assert 'id="pull"' in html and 'id="plan"' in html and "What happened in this pull" in html
    assert 'id="pull"' not in raidplan.render(p, "Boss", "mythic", "ABC", "kill")
