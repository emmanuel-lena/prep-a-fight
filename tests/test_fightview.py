import json
import re

from paf import fightview
from paf.actions import Action
from paf.fight import Fight
from paf.optimize import Plan, Rule
from paf.prep_report import PrepData


def sheet(monkeypatch):
    d = PrepData("Boss", "heroic", "Subtlety", "Char", kills=40, duration=300)
    d.phases = [("Stage One", 0.0), ("Stage Two", 150.0)]
    d.fight = Fight("B", 300)
    d.cd_names = {"shadow_blades": "Shadow Blades", "potion": "Potion"}
    d.icons = {"Shadow Blades": "inv_knife_1h_grimbatolraid_d_03"}
    d.links = {"Shadow Blades": "spell=121471"}
    d.boss_casts = [("Soul Transfer", [21.0, 160.0])]
    d.waves = [(50.0, 4, 20.0, "Amani")]
    d.actions = [Action("kill", "Amani", "Kill the Amani (~4 per kill)")]
    d.optimized = [Plan("boss", {"shadow_blades": Rule("hold_adds_45", "", None)}, 4.0, 0.2)]
    presses = [(0.2, ["Potion"]), (52, ["Shadow Blades"]), (200, ["Shadow Blades"])]
    monkeypatch.setattr("paf.optimize.plan_moments", lambda plan, fight, names: presses)
    monkeypatch.setattr("paf.gamedata.spell_durations", lambda: {121471: 16.0})
    return d


def test_moments_put_the_boss_and_you_together(monkeypatch):
    d = sheet(monkeypatch)
    ms = fightview.moments(d)
    first = ms[0]
    assert first.t < 0 and first.title == "Before the pull" and first.you[0].kind == "pot"  # a pre-pot
    adds = next(m for m in ms if m.t == 50.0)
    assert adds.title == "4 × Amani" and adds.anchor.kind == "adds"
    assert [y.text for y in adds.you] == ["Kill Amani", "Shadow Blades"]  # 52 s shares the adds' row, the job first
    assert next(y for y in adds.you if y.text == "Shadow Blades").dur == 16.0  # its aura, from the game data
    two = next(m for m in ms if m.t == 150.0)
    assert two.title == "Stage Two begins"  # a phase always opens its own row
    assert ms[-1].title == "The kill, around 5:00"


def test_the_page_carries_its_data_and_one_script(monkeypatch):
    d = sheet(monkeypatch)
    page = fightview.html(d)
    data = json.loads(re.search(r"var FV=(\{.*?\});</script>", page).group(1))
    assert data["end"] == 300 and [p[0] for p in data["phases"]] == ["Stage One", "Stage Two"]
    assert any(s["k"] == "cd" and s["d"] == 16.0 for s in data["strips"])
    assert page.count("id='c-sync'") == 1 and "aria-keyshortcuts='Control+Shift+Space'" in page
    assert "Your job on this boss" in page and "<b>Kill the Amani</b>" in page
    assert ("<b>Shadow Blades</b> at 0:52, 3:20: keep for the next add wave if it comes within 45 s, otherwise use "
            "it." in page) and "<b>Potion</b> before the pull." in page
    blades = [a for a in data["acts"] if a["n"] == "Shadow Blades"]
    assert blades[0]["t"] == 52 and blades[0]["c"] == "on the 4 × Amani"  # called at its own time, not the row's
    assert [a["k"] for a in data["anchors"]] == ["pull", "cast", "adds", "phase", "cast"]  # what a press can confirm
    assert "<dialog class='ss' id='ss'" in page and "Dig deeper" in page
    assert fightview.JS.strip().startswith("/*") and "</script" not in fightview.JS


def test_movement_is_a_bar_not_an_event(monkeypatch):
    from paf.movement import Movement, Window

    d = sheet(monkeypatch)
    d.movement = Movement(windows=[Window(100.0, 15.0, [("Shadowstep", 0.8)])])
    ms = fightview.moments(d)
    row = next(m for m in ms if m.t == 100.0)
    assert row.anchor is None and [y.text for y in row.you] == ["Shadowstep for the move"]
    data = json.loads(re.search(r"var FV=(\{.*?\});</script>", fightview.html(d)).group(1))
    assert not any(a["k"] == "move" for a in data["anchors"]) and any(s["k"] == "move" for s in data["strips"])


def test_no_fight_no_view():
    assert fightview.html(PrepData("Boss", "heroic", "Subtlety", "Char")) == ""


def test_a_tank_only_cast_is_dimmed_and_never_confirmed(monkeypatch):
    d = sheet(monkeypatch)
    d.ability_roles = {"Soul Transfer": ["tank"]}
    ms = fightview.moments(d)
    first = next(m for m in ms if m.t == 21.0)
    assert first.boss[0].kind == "tank" and first.boss[0].text == "Soul Transfer (tank)" and first.anchor is None
    data = json.loads(re.search(r"var FV=(\{.*?\});</script>", fightview.html(d)).group(1))
    assert "Soul Transfer" not in [a["n"] for a in data["anchors"]]


def test_the_desktop_holds_the_sync_key_only_while_a_fight_plays():
    from paf import desktop

    api = desktop.Api()
    api.sync_key(True)
    assert api.want.is_set()
    api.sync_key(False)
    assert not api.want.is_set()
    assert "__fv" in desktop.SYNC_JS and "sync()" in desktop.SYNC_JS


def test_a_press_no_boss_event_explains_says_why(monkeypatch):
    """Issue #25: the plan's rule, else its cooldown coming back, and what the top players do then."""
    d = sheet(monkeypatch)
    presses = [(0.2, ["Potion"]), (2, ["Shadow Blades"]), (92, ["Shadow Blades"]), (182, ["Shadow Blades"])]
    monkeypatch.setattr("paf.optimize.plan_moments", lambda plan, fight, names: presses)
    d.optimized = [Plan("boss", {"shadow_blades": Rule("default", "", None)}, 0.0, 0.2)]
    d.tops_players = 20
    d.tops_casts = {"shadow_blades": [2.0] * 20 + [98.0] * 16 + [182.0] * 15}
    why = {t: it.why for t, it in fightview.items(d) if it.name == "Shadow Blades"}
    assert why[2] == ""  # the pull says it
    assert why[92] == "as soon as it is ready again; 80% of the top players wait until 1:38"
    assert why[182] == "as soon as it is ready again, like 75% of the top players"
    acts = fightview.data(d, fightview.moments(d), 300)["acts"]
    assert next(a for a in acts if a["t"] == 92)["w"] == why[92]
