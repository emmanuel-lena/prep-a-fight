from paf.corpus.units import aura_windows, rate_ratio
from paf.fight import Fight, Vulnerable
from paf.notes import apply_notes, notes_template, parse_notes

START = 1_000_000


def ev(t, typ, aid, src, tgt=1):
    return {"timestamp": START + t * 1000, "type": typ, "abilityGameID": aid, "sourceID": src, "targetID": tgt}


def test_aura_windows_keeps_enemy_auras_on_the_boss_only():
    events = [ev(10, "applydebuff", 7, 1), ev(30, "removedebuff", 7, 1),     # from the boss itself
              ev(12, "applydebuff", 8, 99), ev(20, "removedebuff", 8, 99),   # from a player: a dot
              ev(40, "applybuff", 9, -1)]                                     # environment, never removed
    w = aura_windows(events, boss_ids={1}, enemy_ids={1, 2}, start=START, end=START + 100_000)
    assert w == {7: [(10.0, 20.0)], 9: [(40.0, 60.0)]}


def test_rate_ratio():
    series = [10, 10, 30, 30, 10, 10]
    assert rate_ratio(series, 10.0, [(20.0, 10.0)]) == 3.0


def test_candidate_amp_needs_confirmation():
    f = Fight("B", 300, candidate_vulnerable=[Vulnerable(100, 20, 1.8, "Frenzy (boss aura)")])
    assert not any("vulnerable" in e for e in f.to_simc())
    assert "# amp Frenzy 1.8" in notes_template(f)
    g, changes = apply_notes(f, parse_notes("amp Frenzy 1.5\n"))
    assert [(v.start, v.multiplier) for v in g.vulnerable] == [(100, 1.5)]
    assert any("vulnerable,first=100" in e for e in g.to_simc())
