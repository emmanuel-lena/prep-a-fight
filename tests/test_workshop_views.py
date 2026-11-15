"""The tool result pages (paf.workshop_views): what each one says and how it draws it."""

from paf import theme
from paf import workshop_views as wv


def test_a_list_with_no_loss_draws_its_bars_from_the_left_edge():
    assert "class='gbar u'" in wv._bar(1.0, 2.0, signed=False) and "width:50.0%" in wv._bar(1.0, 2.0, signed=False)
    assert "class='gbar'" in wv._bar(-1.0, 2.0) and "width:25.0%" in wv._bar(-1.0, 2.0)
    page = wv.render({"kind": "loot", "error": 0.1, "ilvl": 300, "bosses": ["A", "B"], "rows": [
        {"name": "Ring", "slot": "finger1", "boss": "A", "gain": 1.0, "item_id": 0}], "ev": [
        {"boss": "A", "ev": 0.2, "n": 1}, {"boss": "B", "ev": 0.1, "n": 1}]})
    assert "class='gbar'>" not in page and page.count("gbar u") == 3  # the farm list and "which boss is worth it"
    assert "Ring 1" in page  # a slot as the game says it, not "finger1"


def test_the_class_colour_never_encodes_a_state():
    css = theme.style("workshop-views")
    assert "var(--accent)" not in css  # the Class Signs Rule: covered, ready, put on it... are neutral


def test_an_enchant_within_the_noise_is_muted_and_listed_last():
    page = wv.enchant_table({"error": 0.2, "rows": [
        {"kind": "enchant", "slot": "feet", "name": "Small", "id": 1, "share": 0.2, "gain": 0.1, "pick": False},
        {"kind": "enchant", "slot": "finger1", "name": "Real", "id": 2, "share": 0.2, "gain": -0.5, "pick": False},
        {"kind": "gem", "slot": "", "name": "Pick", "id": 3, "share": 0.6, "gain": 0.6, "pick": True}]})
    assert page.index("Pick") < page.index("Real") < page.index("Small")
    assert "&asymp; +0.10%" in page and "class=noise" in page
    assert "<td class='n neg'>&minus;0.50%</td>" in page and "Ring 1" in page and "finger1" not in page
