from paf.talent_sim import build_diff
from paf.talents import ALPHABET, _Bits


def test_bits_are_read_lsb_first():
    # 'B' = 1 -> first bit 1; 'C' = 2 -> second bit 1
    b = _Bits("BC")
    assert b.read(1) == 1
    assert b.read(5) == 0
    assert b.read(2) == 2  # bits 0,1 of 'C' = 0,1 -> value 2
    assert b.remaining == 4
    assert ALPHABET.index("/") == 63


def test_build_diff():
    names = {1: "A", 2: "B", 3: "C"}
    add, drop = build_diff({1, 2}, {2, 3}, names)
    assert add == ["C"] and drop == ["A"]


def test_an_import_string_round_trips(monkeypatch):
    from paf import talents
    from paf.talents import Choice

    nodes = [11, 12, 13, 14]
    monkeypatch.setattr(talents, "_tree_data", lambda: (
        {n: 7 for n in nodes}, {11: [101], 12: [102], 13: [103, 104], 14: [105, 106]},
        {101: 1, 102: 3, 103: 1, 104: 1, 105: 1, 106: 1}, {7: nodes}))
    monkeypatch.setattr(talents, "_node_types", lambda: {13: "2"})  # 14 lists two entries but is no choice
    choices = [Choice(11, 101, 1, True), Choice(12, 102, 2), Choice(13, 104, 1), Choice(14, 105, 1)]
    assert talents.decode(talents.encode(260, choices, 7), 7) == (260, choices)
