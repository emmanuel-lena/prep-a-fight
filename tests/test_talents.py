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
