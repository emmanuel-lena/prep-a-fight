from paf.droptimizer import LootItem, boss_ev, item_options, usable_loot
from paf.profile import parse_simc_export

LOOT = {1: ("Boss A", [10, 11, 12, 13, 14, 15]), 2: ("Boss B", [20])}
CLASSES = {
    10: (4, 3, 1),   # mail helm -> ok for a shaman
    11: (4, 4, 1),   # plate helm -> no
    12: (2, 15, 13),  # dagger -> ok
    13: (2, 8, 17),  # 2H sword -> no for a shaman
    14: (4, 0, 12),  # trinket
    15: (4, 6, 14),  # shield
    20: (4, 3, 7),   # mail legs
}
NAMES = {10: ("Helm", -1), 11: ("Plate", -1), 12: ("Dagger", -1), 13: ("Sword", -1), 14: ("Trinket", -1),
         15: ("Shield", -1), 20: ("Legs", 1)}  # legs: warrior only (class mask bit 1)


def test_usable_loot_filters_armor_weapons_and_class_mask():
    items = usable_loot([1, 2], "shaman", LOOT, CLASSES, NAMES)
    assert [(i.item_id, i.slot, i.boss) for i in items] == [
        (10, "head", "Boss A"), (12, "main_hand", "Boss A"), (14, "trinket", "Boss A"), (15, "off_hand", "Boss A")]


def test_item_options_copy_enchant_and_try_both_trinket_slots():
    prof = parse_simc_export('shaman="T"\nhead=,id=1,enchant_id=77\ntrinket1=,id=2\ntrinket2=,id=3\n')
    head = LootItem(10, "Helm", "head", "A")
    assert item_options(head, prof, 320) == [["head=,id=10,ilevel=320,enchant_id=77"]]
    tr = LootItem(14, "Trinket", "trinket", "A")
    assert len(item_options(tr, prof, 320)) == 2


def test_boss_ev_counts_losses_as_zero():
    a = LootItem(1, "a", "head", "A", {"f": 2.0})
    b = LootItem(2, "b", "head", "A", {"f": -1.0})
    assert boss_ev([a, b], {"f": 1.0}) == [("A", 1.0, 2)]
