from paf import movement, simple
from paf.corpus.timeline import Ability
from paf.fight import Fight, Window
from paf.prep_report import PrepData


class TL:
    abilities = [Ability(1, "Spiritwalker's Grace", 1.0, 3), Ability(2, "Ascendance", 1.0, 3)]
    players = [{"casts": {1: [41.0, 170.0], 2: [1.0]}}, {"casts": {1: [44.0]}}, {"casts": {2: [1.0]}}]


def test_mobility_spells_of_the_strategy_windows():
    wins = movement.mobility(TL, [Window(43, 26), Window(170, 57), Window(300, 3)])
    assert [(w.start, w.spells) for w in wins] == [(43, [("Spiritwalker's Grace", 0.67)]), (170, [])]  # 3 s: too short
    assert movement.mobility(None, [Window(43, 26)])[0].spells == []


def test_cost_per_10_seconds():
    assert movement.cost(100_000, 95_000, 50) == 1.0
    assert movement.cost(100_000, 101_000, 50) == 0.0 and movement.cost(0, 1, 1) is None


def test_movement_card_and_rows():
    d = PrepData("Boss", "mythic", "Elemental", "Char", duration=300)
    d.fight = Fight("B", 300)
    d.movement = movement.Movement([movement.Window(43, 26, [("Spiritwalker's Grace", 0.67)])], 1.72, 0.23, 0.49)
    card = simple.move_card(d)
    assert "1 moments where most top players move (26 s in all)" in card and "about 1.7% of your DPS" in card
    assert "lose only about 0.4% per 10 s" in card and "Spiritwalker&#x27;s Grace" in card
    view = simple.fight_html(d)
    assert "Everyone moves (26 s)" in view and "Move: it is the strategy" in view and "ability_rogue_sprint" in view
