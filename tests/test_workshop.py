from types import SimpleNamespace

from paf import workshop, workshop_views

ENCS = [SimpleNamespace(id=3470, name="Nek'zali"), SimpleNamespace(id=3497, name="The Lost Explorers")]


def test_the_workshop_speaks_the_players_questions(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    page = workshop.index()
    assert page.count("class='ws-card'") == len(workshop.TOOLS)
    assert "Best gear from your bags" in page and "?raw=1" not in page  # the CLI stays for developers
    form = workshop.tool_page("topgear", ENCS)
    assert "A training dummy (no boss)" in form and "name='objective'" in form and "name='_curated'" in form
    assert workshop.tool_page("not-a-tool", ENCS) is None


def test_curated_forms_make_the_right_command_lines():
    f = {"_curated": ["1"], "boss": ["3470"], "difficulty": ["mythic"], "objective": ["boss"]}
    assert workshop.args("droptimizer", f)[:7] == ["droptimizer", "--boss", "3470", "--fight", "3470", "--difficulty",
                                                    "mythic"]
    assert workshop.args("talents", {"boss": ["3470"], "difficulty": ["heroic"]})[:4] == ["talents", "3470",
                                                                                         "--difficulty", "heroic"]
    assert workshop.args("talents", {"difficulty": ["heroic"]}) is None  # a boss is needed
    assert "--boss" not in workshop.args("topgear", {"boss": [""], "difficulty": ["mythic"]})  # the training dummy


def test_result_views():
    assert workshop_views.run_dir("x\nRuns and best set: C:/runs/a\n").name == "a"
    t = workshop_views.talents({"error": 0.1, "boss": "B", "rows": [
        {"label": "top build D", "players": 5, "gain": 1.46, "take": ["Jet Stream", "Earthquake"],
         "drop": ["Windveil", "Earthquake"], "code": "CYQ"},
        {"label": "top build A", "players": 6, "gain": -0.18, "take": [], "drop": [], "code": ""}]})
    assert "Change 1 talent" in t and "data-copy='CYQ'" in t
    assert "<span>Windveil</span></span><span class='arr' aria-label='becomes'>&rarr;</span>" in t  # the swap shown
    assert "6 of the top players play exactly your build" in t  # build A: no change
    assert "Earthquake" not in t.split("glist")[0]  # on both sides: not a change
    keep = workshop_views.talents({"error": 0.5, "rows": [{"label": "A", "players": 3, "gain": 0.2, "take": [],
                                                           "drop": [], "code": ""}]})
    assert "Keep your talents" in keep
    loot = workshop_views.loot({"error": 0.2, "ilvl": 326, "bosses": ["B"], "ev": [], "rows": [
        {"name": "Shawl", "item_id": 0, "slot": "back", "boss": "B", "gain": 0.43},
        {"name": "Cleaver", "item_id": 0, "slot": "main_hand", "boss": "B", "gain": -17.3}]})
    assert "1 item worth it for you" in loot and "Not upgrades (1)" in loot
    cds = workshop_views.render({"kind": "cooldowns", "plans": [
        {"objective": "boss", "gain": 0.53, "error": 0.06, "rules": [{"cd": "Ascendance", "how": "for the adds"}]}]})
    assert "For boss damage" in cds and "Ascendance" in cds
    assert workshop_views.render({"kind": "unknown"}) is None


def test_top_gear_takes_a_dummys_targets_and_length_and_a_pasted_export(monkeypatch, tmp_path):
    # the owner (2026-10-24): Top Gear as a local Raidbots, its options on the form
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    a = workshop.args("topgear", {"boss": [""], "targets": ["5"], "length": ["180"], "difficulty": ["mythic"],
                                  "simc": ['mage="Alt"\nspec=frost']})
    assert a[a.index("--targets") + 1] == "5" and a[a.index("--length") + 1] == "180"
    pasted = a[a.index("--profile") + 1]
    assert pasted.endswith("pasted.simc") and 'mage="Alt"' in open(pasted, encoding="utf-8").read()
    b = workshop.args("topgear", {"boss": ["3470"], "targets": ["5"], "difficulty": ["mythic"]})
    assert "--targets" not in b and "--boss" in b  # a boss: its own fight, no dummy option
    page = workshop.tool_page("topgear", [])
    assert "name='targets'" in page and "name='length'" in page and "name='simc'" in page


def test_the_gear_tool_says_what_to_equip_then_what_to_farm(monkeypatch, tmp_path):
    # the owner (2026-10-24): "a /simc, a fight, an hour if need be, then what to wear and what to farm"
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    assert workshop.args("gear", {"boss": ["3470"], "difficulty": ["heroic"]})[:3] == ["gear", "--boss", "3470"]
    page = workshop_views.render({"kind": "gear", "fights": ["dummy 5 targets 3 min"], "farm": {
        "error": 0.2, "ilvl": 321, "bosses": ["B"], "ev": [], "rows": [
            {"name": "Shawl", "item_id": 0, "slot": "back", "boss": "B", "gain": 0.43}]}})
    assert "Simmed on a training dummy, 5 targets 3 min." in page and "<h2>Farm</h2>" in page and "Shawl" in page
    assert "<h2>Equip</h2>" not in page  # no bags: no set to say
    assert "Nothing to change" in workshop_views.render({"kind": "gear", "fights": []})
