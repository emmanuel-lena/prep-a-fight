import json

from paf import progress

LOG = """
== Collecting the corpus from Warcraft Logs  [+3s]
Nek'zali: collecting 200 Elemental Shaman kills
  199 ranked kills found (199 new)
  [1/199] 304s, 20 players, 31 adds killed
  [2/199] 435s, 19 players, 41 adds killed
  [10/199] 300s, 20 players, 30 adds killed
"""


def test_corpus_time_left_from_its_own_pace(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    # 10 kills in 5 minutes (from +3 s to +303 s): 189 kills left -> about 95 minutes, plus the next steps
    rows, left = progress.prep_progress(LOG, elapsed=303)
    assert rows[0][2] == "now" and "paced" in rows[0][1]
    nxt = sum(m for p, _, _, m in progress.PREP_STEPS[2:] if not p.startswith(progress.OPTIONAL))
    assert abs(left - (94.5 + nxt)) < 1
    # a quota wait announced on the last line adds its minutes
    _, waiting = progress.prep_progress(LOG + "  quota: 1536/3600 points used, waiting 13 min for the reset...\n",
                                        elapsed=303)
    assert abs(waiting - left - 13) < 0.01


def test_steps_learn_their_duration_on_this_computer(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "step-times.json").write_text(json.dumps({"Ideal cooldown plan": [120, 180, 240]}))
    log = "== Simming your character on the fight  [+10s]\n"
    _, with_history = progress.prep_progress(log, elapsed=10)
    (tmp_path / "web" / "step-times.json").write_text("{}")
    _, without = progress.prep_progress(log, elapsed=10)
    assert abs((without - with_history) - (20 - 3)) < 0.01  # median 3 min instead of the typical 20


def test_clock_saves_step_durations(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    c = progress.Clock()
    c.step("Analyzing the corpus")
    c.marks[-1] = (c.marks[-1][0], c.marks[-1][1] - 30)  # it took 30 s
    c.step("Done")
    c.save()
    assert "== Analyzing the corpus  [+" in capsys.readouterr().out
    hist = progress.history()
    assert list(hist) == ["Analyzing the corpus"] and 29 < hist["Analyzing the corpus"][0] < 32


def test_findings_in_the_players_words():
    log = (LOG + "  199 kills, 4 add waves / targets, duration 6:33\n"
           "  simulated / real DPS of the top players: 0.97 with movement x0.19\n")
    found = progress.findings(log)
    assert found[0] == "199 ranked kills of your spec found."
    assert "6:33, 4 add waves" in found[1] and "97%" in found[2]
