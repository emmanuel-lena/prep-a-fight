from paf.corpus.units import analyze_graph, windows_from_series


def test_windows_from_series():
    assert windows_from_series([0, 1, 2, 0, 0, 3, 0], 2.0) == [(2.0, 4.0), (10.0, 2.0)]


def test_analyze_graph_windows_and_ratio():
    boss = [10] * 10
    heart = [0, 0, 0, 30, 30, 30, 0, 0, 0, 0]
    series = [{"name": "Boss", "type": "Boss", "data": boss},
              {"name": "Heart", "type": "Boss", "data": heart},
              {"name": "Add", "type": "NPC", "data": [1] * 10}]
    rows = analyze_graph(series, "Boss", duration=100.0)
    assert rows == [("Heart", 30.0, 30.0, 3.0)]


def test_analyze_graph_splits_on_leftover_damage():
    boss = [10] * 10
    lord = [0, 20, 20, 20, 1, 1, 20, 20, 20, 0]  # dots only while it is away
    series = [{"name": "Boss", "type": "Boss", "data": boss}, {"name": "Lord", "type": "Boss", "data": lord}]
    rows = analyze_graph(series, "Boss", duration=100.0)
    assert [(r[1], r[2]) for r in rows] == [(10.0, 30.0), (60.0, 30.0)]


def test_analyze_graph_ignores_tiny_units():
    series = [{"name": "Boss", "type": "Boss", "data": [100] * 10},
              {"name": "Totem", "type": "Boss", "data": [0, 1, 1, 0, 0, 0, 0, 0, 0, 0]}]
    assert analyze_graph(series, "Boss", duration=100.0) == []
