from paf.talent_sim import swaps

# entry id -> (name, spell id, node id, x, y)
TREE = {1: ("Spirit Wolf", 11, 100, 0, 0), 2: ("Thunderous Paws", 12, 100, 0, 0),  # one choice node
        3: ("Tempest", 13, 200, 9000, 0), 4: ("Frost Shock", 14, 300, 0, 9000),  # far apart
        5: ("Feedback Loop", 15, 400, 300, 0), 6: ("Feedback Loop", 16, 401, 600, 0),  # two ranks
        7: ("Earthquake", 17, 500, 0, 300), 8: ("Earthquake", 18, 501, 0, 600)}  # a name on two nodes


def test_swaps_pair_your_talent_with_the_new_one():
    out = swaps({1, 3, 7}, {2, 4, 5, 6, 8}, TREE)
    assert (("Spirit Wolf", 11), ("Thunderous Paws", 12)) in out  # the same choice node
    names = [(a[0] if a else None, b[0] if b else None) for a, b in out]
    assert ("Tempest", "Frost Shock") in names or ("Tempest", "Feedback Loop") in names  # a point moved
    assert sum(b and b[0] == "Feedback Loop" for _, b in out) == 1  # two ranks, one line
    assert not any((a and a[0] == "Earthquake") or (b and b[0] == "Earthquake") for a, b in out)


def test_wowhead_links_in_the_players_language(monkeypatch):
    from paf import wowhead

    monkeypatch.setenv("PAF_LANG", "fr")
    assert wowhead.url("spell=12") == ("https://www.wowhead.com/fr/spell=12", "spell=12&domain=fr")
    monkeypatch.setenv("PAF_LANG", "en")
    assert wowhead.url("item=5&ilvl=300") == ("https://www.wowhead.com/item=5", "item=5&ilvl=300")
