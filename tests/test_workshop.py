from types import SimpleNamespace

from paf import workshop, workshop_views

ENCS = [SimpleNamespace(id=3470, name="Nek'zali"), SimpleNamespace(id=3497, name="The Lost Explorers")]


def test_the_workshop_speaks_the_players_questions(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    page = workshop.index()
    assert page.count("class='ws-card'") == len(workshop.TOOLS)
    assert "Best gear from your bags" in page and "?raw=1" in page  # every raw command, folded
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
    assert "Switch to <span>top build D</span>" in t and "data-copy='CYQ'" in t
    assert "+ Jet Stream" in t and "Earthquake" not in t.split("glist")[0]  # on both sides: not a change
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
