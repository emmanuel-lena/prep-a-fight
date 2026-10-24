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
    assert ("<b>Shadow Blades</b> at 0:52, 3:20 <span class='pill hold' title='keep for the next add wave if it comes "
            "within 45 s, otherwise use it'>hold &le;45 s for adds</span>." in page)
    assert "<b>Potion</b> before the pull." in page
    blades = [a for a in data["acts"] if a["n"] == "Shadow Blades"]
    assert blades[0]["t"] == 52 and blades[0]["c"] == "on the 4 × Amani"  # called at its own time, not the row's
    assert [a["k"] for a in data["anchors"]] == ["pull", "cast", "adds", "phase", "cast"]  # what a press can confirm
    assert "<dialog class='ss' id='ss'" in page and "For those who dig" not in page  # the tab is there
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
    assert why[182] == "as soon as it is ready again; 75% of the top players press it then"
    acts = fightview.data(d, fightview.moments(d), 300)["acts"]
    assert next(a for a in acts if a["t"] == 92)["w"] == why[92]
    d.optimized = [Plan("boss", {"shadow_blades": Rule("hold_adds_10", "", None)}, 0.0, 0.2)]  # a held rule: said once
    why = {t: it.why for t, it in fightview.items(d) if it.name == "Shadow Blades"}
    assert why[92].startswith("keep for the next add wave if it comes within 10 s, otherwise use it")
    assert why[182] == "75% of the top players press it then"  # the rule not said again


def test_a_boss_row_says_what_the_journal_tells_damage_dealers(monkeypatch):
    """#28: Sszorak's Dig In row had no instruction; the journal's line for damage dealers names it."""
    d = sheet(monkeypatch)
    d.actions = []
    d.waves = []
    d.boss_casts = [("Dig In", [111.0, 249.0]), ("Ravage", [30.0])]
    d.role_bullets = ["[Dig In] increases Sszorak's damage taken during Howling Maelstrom.",
                      "Venomous Surge inflicts raid-wide damage."]
    dig = [it for _t, it in fightview.items(d) if it.name == "Dig In"]
    assert [it.hint for it in dig] == ["Dig In increases Sszorak's damage taken during Howling Maelstrom.", ""]
    assert not next(it for _t, it in fightview.items(d) if it.name == "Ravage").hint  # not a damage dealer's line
    page = fightview.html(d)
    assert ("class='hint' title='Journal: Dig In increases Sszorak&#x27;s damage taken during Howling Maelstrom.'>"
            "&#128214; journal") in page  # the timeline row: its words on hover, Your job says them
    assert "<b>Dig In</b> at 1:51, 4:09: Dig In increases" in fightview.job_html(d)  # Your job says it, with when
    d.waves = [(24.0, 5, 30.0, "Bubblefin Shorerunner")]
    d.role_bullets = ["[Alluring Bubble] attracts a large group of Bubblefin Shorerunners to rush toward the bubble."]
    assert next(it for _t, it in fightview.items(d) if it.kind == "adds").hint.startswith("Alluring Bubble attracts")
    job = fightview.job_html(d)  # no action names the murlocs: Your job says to kill them, with the journal's why
    assert "<b>Kill the Bubblefin Shorerunners</b> at 0:24.</span>" in job  # the why stays on the fight rows


def test_two_adds_of_one_wave_are_one_kill_row(monkeypatch):
    # Subtlety Rogue, Vashnik (DPS round 10): "Kill Burning Venom" and "Kill Shrouded Venom", both at 0:24
    d = sheet(monkeypatch)
    d.waves = [(24.0, 2, 19.0, "Burning Venom"), (24.1, 5, 8.0, "Shrouded Venom")]  # the logs' 24.0 and 24.1
    d.actions = [Action("kill", "Burning Venom", "Kill the Burning Venom (~6 per kill)"),
                 Action("kill", "Shrouded Venom", "Kill the Shrouded Venom (~15 per kill)")]
    you = [it.text for t, it in fightview.items(d) if t == 24.0 and it.side == "you"]
    assert you == ["Kill Burning Venom and Shrouded Venom"]
    job = fightview.job_html(d)
    assert "Kill Burning Venom and Shrouded Venom at 0:24" in re.sub("<[^>]+>", "", job)


def test_a_long_press_list_reads_as_its_cadence_then_its_exceptions():
    # Elemental, Nek'zali (DPS rounds 16-17): "every 31 s (8 times)" hid the press held for the 2:47 wave
    assert fightview._cadence([0, 31.4, 62.9, 93.7, 123.7, 168.0, 204.9, 235.2]) == (
        "0:00, then about every 31 s to 2:03; then 2:48, 3:24, 3:55")
    assert fightview._cadence([10.0, 60.0, 90.0]) == "0:10, 1:00, 1:30"


def test_a_boss_cast_is_a_reason_for_a_defensive_only():
    # Subtlety Rogue, Vashnik (DPS round 17): "Shadow Blades - on Malignant Catalyst", a raid-wide hit
    cast = fightview.Item("boss", "cast", "Malignant Catalyst", "Malignant Catalyst")
    its = [(198.0, cast)]
    assert fightview._ctx(200.0, its, "cd") == ""
    assert fightview._ctx(200.0, its, "def") == "on Malignant Catalyst"


def test_the_kill_and_a_press_a_few_seconds_on_open_their_own_rows(monkeypatch):
    """Round 39: the kill at 4:01 on the 3:57 Malignant Catalyst row, Shadow Blades 1:40 on the 1:34 row."""
    from paf import fightview

    its = [(94.0, fightview.Item("boss", "cast", "Exploding Infection", "Exploding Infection")),
           (100.0, fightview.Item("you", "cd", "Shadow Blades", "Shadow Blades")),
           (237.0, fightview.Item("boss", "cast", "Malignant Catalyst", "Malignant Catalyst")),
           (241.0, fightview.Item("boss", "kill", "The kill", "The kill, around 4:01"))]
    monkeypatch.setattr(fightview, "items", lambda d: its)
    assert [m.t for m in fightview.moments(None)] == [94.0, 100.0, 237.0, 241.0]
