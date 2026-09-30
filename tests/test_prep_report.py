from paf.prep_report import PrepData, render


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
