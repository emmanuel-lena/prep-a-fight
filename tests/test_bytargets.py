from pathlib import Path
from types import SimpleNamespace

from paf import bytargets, talent_sim, workshop, workshop_views
from paf.talent_sim import Build

PROFILE = 'rogue="Me"\nspec=outlaw\ntalents=MINE\nhead=,id=1\n'


def test_a_build_replaces_the_talents_line_or_is_added():
    assert "talents=AOE\n" in bytargets.with_talents(PROFILE, "AOE") and "MINE" not in bytargets.with_talents(
        PROFILE, "AOE")
    assert bytargets.with_talents('rogue="Me"\n', "AOE").endswith("talents=AOE\n")
    assert bytargets.own_code(PROFILE) == "MINE"


def test_the_top_players_builds_of_every_boss_prepared_once_each(monkeypatch):
    # two bosses play the same build: one candidate, named after the boss where most top players play it
    a, b, c = frozenset({1, 2}), frozenset({1, 3}), frozenset({4})
    got = {1: [Build(a, n=5, code="A"), Build(b, n=2, code="B")], 2: [Build(a, n=9, code="A"), Build(c, n=1)]}
    monkeypatch.setattr(talent_sim, "top_builds", lambda con, enc, diff, spec, n: got[enc])
    con = SimpleNamespace(execute=lambda q: SimpleNamespace(fetchall=lambda: [(1, 5, 30), (2, 5, 20)]))
    builds = bytargets.corpus_builds(con, "Outlaw", {1: "Twin Fangs", 2: "Coiled Altar"})
    assert [(x.code, x.label) for x in builds] == [("A", "top players on Coiled Altar"),
                                                   ("B", "top players on Twin Fangs")]  # no code: not simmed


def _row(code, gains, swaps=(("x", 1), ("y", 2))):
    return talent_sim.TalentRow(Build(frozenset({hash(code)}), code=code, label=code, n=3),
                                {f: (g, None) for f, g in gains.items()}, [], [], [list(swaps)] if swaps else [])


def test_a_build_is_taken_on_a_dummy_only_beyond_the_noise():
    counts = [bytargets.Count(n, label) for n, label in bytargets.COUNTS]
    one, two, five = (c.fight for c in counts)
    tc = SimpleNamespace(error=0.2, rows=[
        _row("yours", {one: 0, two: 0, five: 0}, swaps=()),
        _row("cleave", {one: 0.3, two: 2.5, five: 1.0}),  # 0.3%: within the noise (2 x 1.41 x 0.2 = 0.57%)
        _row("aoe", {one: -3.0, two: 1.0, five: 6.0})])
    picks = bytargets.best_rows(tc, counts)
    assert picks[one] is None and picks[two].build.code == "cleave" and picks[five].build.code == "aoe"


def test_each_count_s_set_is_simmed_with_its_talents(monkeypatch, tmp_path):
    counts = [bytargets.Count(n, label) for n, label in bytargets.COUNTS]
    tc = SimpleNamespace(error=0.2, rows=[_row("AOE", {counts[0].fight: -2, counts[1].fight: 0.1,
                                                       counts[2].fight: 5})])
    monkeypatch.setattr(talent_sim, "compare", lambda *a, **k: tc)
    seen = {}

    def topgear(text, pool, fights, run_dir, **kw):
        seen[fights[0].name] = (bytargets.own_code(text), fights[0].lines)
        return SimpleNamespace(fights=fights, combos=[])
    monkeypatch.setattr("paf.topgear.run_topgear", topgear)
    out = bytargets.run(PROFILE, SimpleNamespace(candidates=[1]), [Build(frozenset({0})), Build(frozenset({1}))],
                        300, Path(tmp_path), log=lambda m: None)
    assert seen["dummy 1 target"][0] == "MINE" and seen["dummy 5 targets"][0] == "AOE"
    assert "desired_targets=5" in seen["dummy 5 targets"][1] and "max_time=300" in seen["dummy 5 targets"][1]
    assert [c["talents"] and c["talents"]["code"] for c in out["counts"]] == [None, None, "AOE"]


def test_the_gear_tool_answers_for_each_target_count_in_cards(monkeypatch, tmp_path):
    # the owner (2026-11-12): "if single target wear this, if 2 targets this gear and these talents, if 3+ this"
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    assert "--by-targets" in workshop.args("gear", {"boss": [""], "targets": ["each"], "difficulty": ["heroic"]})
    assert "--targets" not in workshop.args("gear", {"boss": [""], "targets": ["each"]})
    assert "--by-targets" not in workshop.args("gear", {"boss": ["3470"], "targets": ["each"]})  # a boss: its fight
    assert "value='each'" in workshop.tool_page("gear", []) and "value='each'" not in workshop.tool_page("topgear", [])
    ring = {"slot": "finger", "items": [{"name": "Band", "ilvl": 289, "item_id": 0, "source": "bags"}]}
    gear = {"error": 0.2, "rows": [{"gain": 1.4, "changes": [ring]}]}
    aoe = {"label": "top players on Coiled Altar", "players": 6, "code": "AOE", "gain": 5.2,
           "hero": ["Deathstalker", "Trickster"], "swaps": [[["Ruthlessness", 0], ["Blade Rush", 0]]]}
    page = workshop_views.render({"kind": "gear", "by_targets": {"length": 300, "counts": [
        {"targets": 1, "label": "1 target", "talents": None, "gear": gear},
        {"targets": 2, "label": "2 targets", "talents": None, "gear": gear},
        {"targets": 5, "label": "3+ targets", "talents": aoe, "gear": {"error": 0.2, "rows": []}}]}})
    assert page.count("class='bt-card") == 3 and "Same as 1 target." in page  # 2 targets: nothing new
    assert "<s>Deathstalker</s> &rarr; <b>Trickster</b>" in page
    assert "Blade Rush" in page and "data-copy='AOE'" in page and "Band" in page and "what you wear" in page


def test_another_hero_tree_is_one_line_not_a_swap_per_hero_talent(monkeypatch):
    # the owner's Rogue on 5 targets (2026-11-12): Deathstalker to Trickster listed 13 hero swaps among 18
    monkeypatch.setattr("paf.gamedata.hero_trees", lambda: {10: "Deathstalker", 11: "Deathstalker", 20: "Trickster"})
    monkeypatch.setattr("paf.gamedata.talent_entries", lambda: {10: ("Darkest Night", 110, 0, 0, 0),
                                                                11: ("Shadewalker", 111, 0, 0, 0),
                                                                20: ("Unseen Blade", 120, 0, 0, 0)})
    hero, spells = bytargets.hero_change(frozenset({1, 10, 11}), frozenset({2, 20}))
    assert hero == ("Deathstalker", "Trickster") and spells == {110, 111, 120}
    assert bytargets.hero_change(frozenset({1, 10}), frozenset({2, 11}))[0] is None  # the same tree: talents listed
