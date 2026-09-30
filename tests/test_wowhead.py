from paf.profile import parse_simc_export
from paf.wowhead import item_ref, link, linkify, profile_refs, spell_ref


def test_link_and_refs():
    assert item_ref(123, 321, "1/2") == "item=123&ilvl=321&bonus=1:2"
    a = link("Ascendance <x>", spell_ref(114050))
    assert 'href="https://www.wowhead.com/spell=114050"' in a and "Ascendance &lt;x&gt;" in a
    assert link("plain", None) == "plain"


def test_linkify_longest_first_and_whole_words():
    refs = {"Band": "item=1", "Band of the Warlord": "item=2", "ascendance": "spell=3"}
    out = linkify("finger: Band of the Warlord (321) + Band; ascendance, reascendance", refs)
    assert out.count("item=2") == 2 and out.count('data-wowhead="item=1"') == 1  # href + data attr for item=2
    assert out.count('data-wowhead="spell=3"') == 1


def test_profile_refs():
    p = parse_simc_export('shaman="X"\nspec=elemental\n# Hat (321)\nhead=,id=10,bonus_id=4/5\n')
    assert profile_refs(p) == {"Hat": "item=10&ilvl=321&bonus=4:5"}
