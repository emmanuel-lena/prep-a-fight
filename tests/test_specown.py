from paf import specown

EXPORT = """rogue="T"
level=90
race=human
region=eu
server=x
spec=assassination
talents=ABC
head=,id=1001,bonus_id=1
main_hand=,id=5001
off_hand=,id=5002

### Gear from Bags
# Staff (330)
# main_hand=,id=5003
"""


def test_your_character_as_another_spec_wears_what_you_wear():
    # issue #35: your own items in the other spec, not the top players' set at 334
    text = specown.spec_text(EXPORT, "Subtlety", ["talents=XYZ"])
    assert "spec=subtlety" in text and "talents=XYZ" in text and "talents=ABC" not in text
    assert "head=,id=1001,bonus_id=1" in text and "main_hand=,id=5001" in text and "id=5003" not in text


def test_an_item_of_another_main_stat_is_not_that_specs():
    primary = {5001: {"agi"}, 5003: {"int"}, 7: {"str", "agi", "int"}}
    assert specown.fits(5001, "agi", primary) and not specown.fits(5003, "agi", primary)
    assert specown.fits(9, "agi", primary) and specown.fits(7, "agi", primary)  # a ring; a mixed-stat item
