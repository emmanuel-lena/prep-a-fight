from paf.profile import parse_simc_export
from paf.validate import profile_from_log


def test_a_profile_read_from_a_log_has_item_levels():
    # issue #17: a character imported from Warcraft Logs had no item level, the loot step crashed
    gear = [{"id": 271483, "name": "Serpent Crown", "itemLevel": "321", "bonusIDs": ["13334"]},
            {"id": 268265, "name": "Aqirbane Reliquary", "itemLevel": 334}]
    p = parse_simc_export(profile_from_log("Someone", "Shaman", "Elemental", "orc", "CYQ", gear))
    assert p.equipped["head"].ilvl == 321 and p.equipped["neck"].ilvl == 334
