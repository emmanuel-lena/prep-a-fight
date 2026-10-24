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
    assert ("<b>Shadow Blades</b> <time class='tc'>0:52</time><time class='tc'>3:20</time> <span class='pill hold' "
            "title='hold for the next add wave if within 45 s, else use it'>hold &le;45 s for adds</span>" in page)
    assert "<b>Potion</b> <span class='pill' title='before the pull'>pre-pull</span>" in page  # chips, not sentences
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
    assert why[92] == "◷ on cooldown; 80% of the top players wait until 1:38"
    assert why[182] == "◷ on cooldown; 75% of the top players press it then"
    acts = fightview.data(d, fightview.moments(d), 300)["acts"]
    assert next(a for a in acts if a["t"] == 92)["w"] == why[92]
    d.optimized = [Plan("boss", {"shadow_blades": Rule("hold_adds_10", "", None)}, 0.0, 0.2)]  # a held rule: said once
    why = {t: it.why for t, it in fightview.items(d) if it.name == "Shadow Blades"}
    assert why[92].startswith("hold ≤10 s for adds")
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
    job = fightview.job_html(d)  # Your job names it with when, its words on the book's hover
    assert "<b>Dig In</b> <time class='tc'>1:51</time><time class='tc'>4:09</time>" in job
    assert "title='Journal: Dig In increases" in job
    d.waves = [(24.0, 5, 30.0, "Bubblefin Shorerunner")]
    d.role_bullets = ["[Alluring Bubble] attracts a large group of Bubblefin Shorerunners to rush toward the bubble."]
    assert next(it for _t, it in fightview.items(d) if it.kind == "adds").hint.startswith("Alluring Bubble attracts")
    job = fightview.job_html(d)  # no action names the murlocs: Your job says to kill them, with the journal's why
    assert "<b>Kill the Bubblefin Shorerunners</b> <time class='tc'>0:24</time></span>" in job  # the why: fight rows


def test_two_adds_of_one_wave_are_one_kill_row(monkeypatch):
    # Subtlety Rogue, Vashnik (DPS round 10): "Kill Burning Venom" and "Kill Shrouded Venom", both at 0:24
    d = sheet(monkeypatch)
    d.waves = [(24.0, 2, 19.0, "Burning Venom"), (24.1, 5, 8.0, "Shrouded Venom")]  # the logs' 24.0 and 24.1
    d.actions = [Action("kill", "Burning Venom", "Kill the Burning Venom (~6 per kill)"),
                 Action("kill", "Shrouded Venom", "Kill the Shrouded Venom (~15 per kill)")]
    you = [it.text for t, it in fightview.items(d) if t == 24.0 and it.side == "you"]
    assert you == ["Kill Burning Venom and Shrouded Venom"]
    job = fightview.job_html(d)
    assert "<b>Kill Burning Venom and Shrouded Venom</b> <time class='tc'>0:24</time>" in job


def test_a_long_press_list_reads_as_its_cadence_then_its_exceptions():
    # Elemental, Nek'zali (DPS rounds 16-17): "every 31 s (8 times)" hid the press held for the 2:47 wave
    chips = fightview._cadence_chips([0, 31.4, 62.9, 93.7, 123.7, 168.0, 204.9, 235.2])  # Your job's form
    assert re.sub("<[^>]+>", " ", chips).split() == ["0:00", "&#10227;", "31", "s", "&rarr;", "2:03", "2:48", "3:24",
                                                     "3:55"]
    assert re.sub("<[^>]+>", " ", fightview._cadence_chips([10.0, 60.0, 90.0])).split() == ["0:10", "1:00", "1:30"]


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


def test_two_add_waves_at_one_moment_are_one_row():
    """Fresh DPS review: '2 × Burning Venom lasts 21 s' and '5 × Shrouded Venom lasts 8 s' on two rows at 0:24."""
    from types import SimpleNamespace

    from paf import fightview

    d = SimpleNamespace(waves=[(24.0, 2, 21.0, "Burning Venom"), (24.0, 5, 8.0, "Shrouded Venom")], fight=None,
                        duration=241, actions=[], boss_casts=[], icons={}, phases=[], lust=None, movement=None,
                        defensives=None, cd_names={}, precast=set(), plan_timeline=[], mech_times={},
                        ability_roles={}, optimized=[], tops_casts={}, tops_players=0, goal="auto", raid=None,
                        plans=[], timeline=None, links={})
    adds = [x for _t, x in fightview.items(d) if x.kind == "adds"]
    text = adds[0].text.replace("\u00a0", " ")  # each unit unbreakable
    assert len(adds) == 1 and text == "2 × Burning Venom (21 s) · 5 × Shrouded Venom (8 s)"


def test_a_press_most_top_players_make_elsewhere_is_flagged_on_its_row(monkeypatch):
    # Subtlety Rogue, Vashnik (fresh DPS review): Shadow Blades 3:20, 64% of the top players at about 3:13
    d = sheet(monkeypatch)
    d.tops_casts, d.tops_players = {"shadow_blades": [193.0] * 64 + [200.0] * 5}, 100
    assert fightview._tops_off(d, "Shadow Blades", 200.0) == "⚠ 64% of the top players at about 3:13"
    why = fightview._why(d, "Shadow Blades", 200.0, [2.0, 100.0, 200.0])  # 3:13 out of reach after 1:40: no
    assert why.endswith("⚠ 64% of the top players at about 3:13 (their cycle runs ~7 s ahead)")  # said
    # Elemental, Nek'zali (fresh DPS review): the tops' 1:37 is the 1:33 press's, not the 2:03's
    d.tops_casts = {"ancestral_swiftness": [97.0] * 74 + [125.0] * 10}
    assert "⚠" not in fightview._why(d, "Ancestral Swiftness", 123.0, [2.0, 33.0, 64.0, 93.0, 123.0])
    assert fightview._tops_off(d, "Ancestral Swiftness", 123.0, [93.0, 123.0]) == ""
    d.tops_casts = {"shadow_blades": [193.0] * 64 + [200.0] * 30}
    assert fightview._tops_off(d, "Shadow Blades", 200.0) == ""  # a fair share press it then too


def test_the_fight_tab_shows_the_opener_as_simc_plays_it(monkeypatch, tmp_path):
    # issue #39 (a Frost Mage tester): the first 40 s of the plan, every cast in order
    from paf import optimize

    log = tmp_path / "boss-pull.log"
    log.write_text("0.000 Player 'X' performs Action 'flask' (0) (100)\n"
                   "0.000 Player 'X' performs Action 'shadow_blades' (121471) (100)\n"  # precombat
                   "0.000 Player 'X_pet' schedules execute for Action 'bite' (17253)\n"  # a pet's
                   "1.010 Player 'X' schedules execute for Action 'eviscerate' (196819)\n"
                   "1.010 Player 'X' performs Action 'eviscerate' (196819) (40)\n"
                   "1.200 Player 'X' performs Action 'shadow_strike' (1) (40)\n"  # a proc: not scheduled
                   "1.500 Player 'X' schedules execute for Action 'eviscerate_overload' (2)\n"
                   "41.000 Player 'X' schedules execute for Action 'eviscerate' (196819)\n", encoding="utf-8")
    monkeypatch.setattr("paf.gamedata.spell_names", lambda locale="": {121471: "Shadow Blades", 196819: "Eviscerate"})
    casts = optimize.opener(log)
    assert casts == [(0.0, "Shadow Blades", 121471), (1.01, "Eviscerate", 196819)]  # no consumable, no swing, ≤40 s
    d = sheet(monkeypatch)
    d.optimized[0].opener = casts
    d.lust = 0.0
    html = fightview.opener_html(d)
    assert "Bloodlust at the pull" in html and html.count("<li ") == 2
    assert "<li title='Shadow Blades 0:00'>" in html and "<li title='Eviscerate 0:01'>" in html
