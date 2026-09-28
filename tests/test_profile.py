from paf.profile import looks_like_export, parse_simc_export

EXPORT = """﻿# Testchar - Elemental - 2026-09-28 20:00 - EU/Somewhere
# SimC Addon 12.1.0-02
# WoW 12.1.0.69933, TOC 120100
# Requires SimulationCraft 1210-01 or newer

shaman="Testchar"
level=90
race=dwarf
region=eu
server=somewhere
role=spell
professions=alchemy=100/herbalism=100
spec=elemental

talents=ABCDEF

# Some Helm (318)
head=,id=271483,bonus_id=1/2/3
neck=,id=100,bonus_id=4,gem_id=5
shoulder=,id=271481,enchant_id=6
main_hand=,id=200,enchant_id=7
off_hand=,id=268262

### Gear from Bags
#
# Vile Vial (318)
# trinket1=,id=273796,bonus_id=1/2
#
# Big Staff (311)
# upgrade_levels=2
# main_hand=,id=300,bonus_id=9

### Weekly Reward Choices
#
# Gebbo's Bottomless Bag (318)
# trinket1=,id=270164,bonus_id=8
### End of Weekly Reward Choices

### Linked gear
#
# Jan'thrazet
# main_hand=,id=271092

### Additional Character Info
#
# upgrade_currencies=c:1:2
"""


def test_header_and_equipped():
    p = parse_simc_export(EXPORT)
    assert (p.class_name, p.name, p.spec) == ("shaman", "Testchar", "elemental")
    assert p.header["talents"] == "ABCDEF"
    assert list(p.equipped) == ["head", "neck", "shoulder", "main_hand", "off_hand"]
    assert p.equipped["head"].item_id == 271483
    assert p.equipped["neck"].fields["gem_id"] == "5"
    assert p.equipped["off_hand"].simc() == "off_hand=,id=268262"


def test_candidates_by_source():
    p = parse_simc_export(EXPORT)
    bags = p.by_source("bags")
    assert [(i.slot, i.name, i.ilvl, i.item_id) for i in bags] == [
        ("trinket1", "Vile Vial", 318, 273796),
        ("main_hand", "Big Staff", 311, 300),
    ]
    vault = p.by_source("vault")
    assert [(i.name, i.item_id) for i in vault] == [("Gebbo's Bottomless Bag", 270164)]
    linked = p.by_source("linked")
    assert [(i.name, i.ilvl, i.item_id) for i in linked] == [("Jan'thrazet", None, 271092)]
    assert len(p.candidates) == 4  # nothing picked up from "Additional Character Info"


def test_looks_like_export():
    assert looks_like_export(EXPORT)
    assert not looks_like_export("hello world")
