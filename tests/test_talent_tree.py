from paf import talent_tree
from paf.talent_tree import Talent, Tree

QUERY = """SimulationCraft
Name         : Root
Entry        : 1
Node         : 10
Tree         : class (1)
Req. Points  : 0
Max Rank     : 1
Subtree      : 0

Name         : Two Ranks
Entry        : 2
Node         : 20
Tree         : class (1)
Req. Points  : 0
Max Rank     : 2
Subtree      : 0

Name         : Behind A Gate
Entry        : 3
Node         : 30
Tree         : class (1)
Req. Points  : 3
Max Rank     : 1
Subtree      : 0

Name         : Pick A
Entry        : 4
Node         : 40
Tree         : spec (2)
Spec         : subtlety (261)
Req. Points  : 0
Max Rank     : 1
Subtree      : 0

Name         : Pick B
Entry        : 5
Node         : 40
Tree         : spec (2)
Spec         : subtlety (261)
Req. Points  : 0
Max Rank     : 1
Subtree      : 0

Name         : Outlaw Only
Entry        : 6
Node         : 60
Tree         : spec (2)
Spec         : outlaw (260)
Req. Points  : 0
Max Rank     : 1
Subtree      : 0

Name         : Hero One
Entry        : 7
Node         : 70
Tree         : hero (3)
Spec         : outlaw (260), subtlety (261)
Req. Points  : 1
Max Rank     : 1
Subtree      : 51

Name         : Hero Two
Entry        : 8
Node         : 80
Tree         : hero (3)
Spec         : assassination (259), subtlety (261)
Req. Points  : 1
Max Rank     : 1
Subtree      : 53

Name         : Dragon-Bone Dice
Entry        : 9
Node         : 90
Tree         : spec (2)
Spec         : subtlety (261)
Req. Points  : 0
Max Rank     : 1
Subtree      : 0
"""


def tree() -> Tree:
    talents = talent_tree.parse_query(QUERY)
    return Tree(talents, {20: {10}, 30: {20}})  # Root -> Two Ranks -> Behind A Gate


def test_the_query_gives_each_talent_its_node_tree_and_specs():
    t = talent_tree.parse_query(QUERY)
    assert t[4] == Talent(4, 40, "Pick A", "spec", frozenset({"subtlety"}), 0, 1, 0)
    assert t[7].specs == {"outlaw", "subtlety"} and t[7].subtree == 51 and t[1].specs == frozenset()


def test_a_build_follows_the_links_the_gates_and_the_hero_tree():
    tr = tree()
    ok = {10: (1, 1), 20: (2, 2), 30: (3, 1), 40: (4, 1), 70: (7, 1)}
    assert tr.problems(ok, "subtlety") == []
    assert tr.problems(ok, "subtlety", {"class": 4, "spec": 1, "hero": 1}) == []
    assert tr.problems(ok, "subtlety", {"class": 5, "spec": 1, "hero": 1}) == ["class: 4 points of 5"]
    assert "Behind A Gate: no parent at max rank" in tr.problems({10: (1, 1), 20: (2, 1), 30: (3, 1)}, "subtlety")
    assert "Behind A Gate: 2 of the 3 points its gate needs" in tr.problems({20: (2, 2), 30: (3, 1)}, "subtlety")
    assert tr.problems({60: (6, 1)}, "subtlety") == ["Outlaw Only: not a talent of this spec"]
    assert tr.problems({70: (7, 1), 80: (8, 1)}, "subtlety") == ["nodes of two hero trees"]


def test_the_moves_of_one_point_stay_in_the_rules():
    tr = tree()
    build = {10: (1, 1), 20: (2, 1), 40: (4, 1)}
    adds = [b for b in tr.additions(build, "subtlety")]
    assert {10: (1, 1), 20: (2, 2), 40: (4, 1)} in adds  # a second rank
    assert not any(30 in b for b in adds)  # the gate needs 3 points and its parent maxed
    assert not any(60 in b for b in adds)  # another spec's talent
    assert any(70 in b for b in adds) and any(80 in b for b in adds)  # either hero tree while none is taken
    removed = tr.removals(build, "subtlety")
    assert {20: (2, 1), 40: (4, 1)} not in removed  # Two Ranks would lose its parent
    assert {10: (1, 1), 40: (4, 1)} in removed
    assert tr.flips(build, "subtlety") == [{10: (1, 1), 20: (2, 1), 40: (5, 1)}]
    with_hero = {**build, 70: (7, 1)}
    assert not any(80 in b for b in tr.additions(with_hero, "subtlety"))  # one hero tree


def test_a_build_goes_to_simc_as_an_import_string_with_its_hero_tree(monkeypatch):
    from paf import talents
    from paf.talents import Choice

    # the game's tree: nodes 10..90 and the hero choice 99 (its entries 97 -> hero tree 51, 98 -> 53)
    nodes = [10, 20, 30, 40, 60, 70, 80, 90, 99]
    entries = {10: [1], 20: [2], 30: [3], 40: [4, 5], 60: [6], 70: [7], 80: [8], 90: [9], 99: [97, 98]}
    ranks = {1: 1, 2: 2, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 97: 1, 98: 1}
    monkeypatch.setattr(talents, "_tree_data", lambda: ({n: 5 for n in nodes}, entries, ranks, {5: nodes}))
    monkeypatch.setattr(talents, "_node_types", lambda: {40: "2", 99: "3"})
    monkeypatch.setattr(talents, "tree_for_entries", lambda ids: 5)
    tr = tree()
    tr.talents[97] = Talent(97, 99, "0", "selection", frozenset({"subtlety"}), 0, 1, 51)
    tr.talents[98] = Talent(98, 99, "0", "selection", frozenset({"subtlety"}), 0, 1, 53)
    tr.by_node[99] = [tr.talents[97], tr.talents[98]]
    reference = talents.encode(261, [Choice(10, 1, 1, True), Choice(99, 98, 1), Choice(80, 8, 1)], 5)
    build = {10: (1, 1), 20: (2, 1), 40: (5, 1), 70: (7, 1)}
    spec, choices = talents.decode(tr.loadout(build, reference), 5)
    got = {c.node_id: (c.entry_id, c.rank, c.granted) for c in choices}
    assert spec == 261 and got == {10: (1, 1, True), 20: (2, 1, False), 40: (5, 1, False), 70: (7, 1, False),
                                   99: (97, 1, False)}  # the hero choice follows the build's hero tree
    assert tr.from_loadout(tr.loadout(build, reference)) == build
