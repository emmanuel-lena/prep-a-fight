from types import SimpleNamespace

from paf import stagetime


def test_a_late_stage_lines_up_on_its_median_start():
    # Nek'zali heroic (round 100): Stage Two from 2:34 to 3:30; its waves +50 s and +80 s into it, smeared on the pull
    clk = stagetime.Clock({("a", 1): {1: 0.0, 3: 154.0}, ("b", 1): {1: 0.0, 3: 210.0}, ("c", 1): {1: 0.0, 3: 185.0}})
    assert clk.med[3] == 185.0
    assert clk.at(("a", 1), 204.0) == 235.0 and clk.at(("b", 1), 260.0) == 235.0  # +50 s: one time
    assert clk.at(("a", 1), 100.0) == 100.0  # Stage One stays in pull time
    assert clk.at(("b", 1), 195.0) is None  # its Stage One past the median Stage Two start: left out
    assert clk.at(("z", 1), 77.0) == 77.0  # a kill with no stage read: its pull time


def test_a_timeline_in_stage_time():
    clk = stagetime.Clock({("a", 1): {1: 0.0, 3: 154.0}, ("b", 1): {1: 0.0, 3: 216.0}})
    tl = SimpleNamespace(duration=300.0, phases=[("Stage One", 0.0, False), ("Stage Two", 190.0, False)],
                         players=[{"kill": ("a", 1), "duration": 280.0, "casts": {1: [30.0, 210.0]}},
                                  {"kill": ("b", 1), "duration": 330.0, "casts": {1: [30.0, 272.0]}}])
    out = stagetime.warp(tl, clk)
    assert [p["casts"][1] for p in out.players] == [[30.0, 241.0], [30.0, 241.0]]
    assert out.phases[1][1] == 185.0 and tl.players[0]["casts"][1] == [30.0, 210.0]  # the timeline left as it is
