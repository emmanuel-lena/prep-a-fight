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


def test_the_fight_reads_as_lanes_on_one_clock(monkeypatch):
    # the owner (2026-11-12): "a big wall"; the fight on one screen, a lane a spell, yours first
    d = sheet(monkeypatch)
    tl = fightview.timeline(d)
    lanes = {lane.names[0]: lane for lane in tl.you}
    assert [lane.kind for lane in tl.you] == ["cd", "pot", "kill"]
    blades = lanes["Shadow Blades"]
    assert [(m.t, m.dur, m.label) for m in blades.marks] == [(52.0, 16.0, "0:52"), (200.0, 16.0, "3:20")]
    assert lanes["Potion"].marks[0].label == "pre"  # a pre-pot
    kill = lanes["Kill Amani"]
    assert kill.sub == "1 wave · 4 adds" and kill.marks[0].count == "4" and kill.marks[0].dur == 20.0
    assert [n for n, _a, _b in tl.phases] == ["Stage One", "Stage Two"]
    assert not tl.boss and [x.name for _t, x in tl.others] == ["Soul Transfer", "Soul Transfer"]  # nothing of yours


def test_the_page_carries_its_data_and_one_script(monkeypatch):
    d = sheet(monkeypatch)
    page = fightview.html(d)
    data = json.loads(re.search(r"var FV=(\{.*?\});</script>", page).group(1))
    assert data["end"] == 300 and [p[0] for p in data["phases"]] == ["Stage One", "Stage Two"]
    assert page.count("id='c-sync'") == 1 and "aria-keyshortcuts='Control+Shift+Space'" in page
    assert "<dialog class='lv' id='ss'" in page and "id='ss-open'" in page and "aria-keyshortcuts='L'" in page
    assert "Your job on this boss" not in page and "class='ftl'" in page  # one timeline, no list beside it
    blades = [a for a in data["acts"] if a["n"] == "Shadow Blades"]
    assert blades[0]["t"] == 52 and blades[0]["c"] == "on the 4 × Amani"  # called at its own time
    assert [a["k"] for a in data["anchors"]] == ["pull", "cast", "adds", "phase", "cast"]  # what a press can confirm
    assert "Burst" not in page  # one press at a time: no burst to say
    assert fightview.JS.strip().startswith("/*") and "</script" not in fightview.JS


def test_movement_is_a_bar_not_an_event(monkeypatch):
    from paf.movement import Movement, Window

    d = sheet(monkeypatch)
    d.movement = Movement(windows=[Window(100.0, 15.0, [("Shadowstep", 0.8)])])
    tl = fightview.timeline(d)
    assert [m[:2] for m in tl.moves] == [(100.0, 115.0)] and any(lane.kind == "move" and lane.names == ["Shadowstep"]
                                                                 for lane in tl.you)
    data = json.loads(re.search(r"var FV=(\{.*?\});</script>", fightview.html(d)).group(1))
    assert not any(a["k"] == "move" for a in data["anchors"])
    assert "The top players move 1:40 to 1:55 (15 s)\nNo boss spell starts it" in fightview.html(d)
    assert "Everyone moves" not in fightview.html(d)  # the owner (2026-11-14): "everyone moves" says nothing
    d.movement = Movement(windows=[Window(158.0, 10.0, [])])  # Soul Transfer cast at 2:40 starts it
    page = fightview.html(d)
    soul = next(lane for lane in fightview.timeline(d).boss if lane.names == ["Soul Transfer"])  # its own lane
    assert soul.sub == "you move 10 s (1 of 2)" and fightview.timeline(d).moves == []
    assert "You move 2:38 to 2:48 (10 s), as the top players do" in soul.marks[1].tip and soul.marks[0].move is None
    data = json.loads(re.search(r"var FV=(\{.*?\});</script>", page).group(1))
    assert [b["n"] for b in data["boss"] if b["k"] == "move"] == ["Move for Soul Transfer"]
    d.movement = Movement(windows=[Window(60.0, 104.0, [])])  # the boss kited around for 104 s: the fight's rhythm
    assert fightview.timeline(d).moves == []


def test_no_fight_no_view():
    assert fightview.html(PrepData("Boss", "heroic", "Subtlety", "Char")) == ""


def test_a_tank_only_cast_is_hidden_and_never_confirmed(monkeypatch):
    d = sheet(monkeypatch)
    d.ability_roles = {"Soul Transfer": ["tank"]}
    tl = fightview.timeline(d)
    assert tl.tank == ["Soul Transfer"] and not tl.others
    page = fightview.html(d)
    assert "Soul Transfer" not in re.sub(r"<script>.*?</script>", "", page, flags=re.S)  # not drawn at all
    data = json.loads(re.search(r"var FV=(\{.*?\});</script>", page).group(1))
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
    acts = fightview.data(d, 300)["acts"]
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
    assert "Dig In increases Sszorak&#x27;s damage taken during Howling Maelstrom." in page  # on its marks' hover
    lane = next(b for b in fightview.timeline(d).boss if b.names == ["Dig In"])
    assert lane.kind == "journal" and lane.sub == "in the journal"
    d.waves = [(24.0, 5, 30.0, "Bubblefin Shorerunner")]
    d.role_bullets = ["[Alluring Bubble] attracts a large group of Bubblefin Shorerunners to rush toward the bubble."]
    assert next(it for _t, it in fightview.items(d) if it.kind == "adds").hint.startswith("Alluring Bubble attracts")
    kill = next(lane for lane in fightview.timeline(d).you if lane.kind == "kill")  # no action names the murlocs
    assert kill.names == ["Kill Bubblefin Shorerunner"] and "Alluring Bubble attracts" in kill.marks[0].tip


def test_two_adds_of_one_wave_are_one_kill_row(monkeypatch):
    # Subtlety Rogue, Vashnik (DPS round 10): "Kill Burning Venom" and "Kill Shrouded Venom", both at 0:24
    d = sheet(monkeypatch)
    d.waves = [(24.0, 2, 19.0, "Burning Venom"), (24.1, 5, 8.0, "Shrouded Venom")]  # the logs' 24.0 and 24.1
    d.actions = [Action("kill", "Burning Venom", "Kill the Burning Venom (~6 per kill)"),
                 Action("kill", "Shrouded Venom", "Kill the Shrouded Venom (~15 per kill)")]
    you = [it.text for t, it in fightview.items(d) if t == 24.0 and it.side == "you"]
    assert you == ["Kill Burning Venom and Shrouded Venom"]


def test_a_boss_cast_is_a_reason_for_a_defensive_only():
    # Subtlety Rogue, Vashnik (DPS round 17): "Shadow Blades - on Malignant Catalyst", a raid-wide hit
    cast = fightview.Item("boss", "cast", "Malignant Catalyst", "Malignant Catalyst")
    its = [(198.0, cast)]
    assert fightview._ctx(200.0, its, "cd") == ""
    assert fightview._ctx(200.0, its, "def") == "on Malignant Catalyst"


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
    assert casts == [(-1.0, "Shadow Blades", 121471), (1.01, "Eviscerate", 196819)]  # precombat -1, no swing
    d = sheet(monkeypatch)
    d.optimized[0].opener = casts
    d.lust = 0.0
    monkeypatch.setattr("paf.gamedata.spell_cooldowns", lambda: {121471: (90.0, 1)})
    html = fightview.opener_html(d)  # a numbered sequence, as a guide writes it; the big cooldowns framed
    assert "Opener <span class='pill'>in Bloodlust</span>" in html
    assert "<li class='big' title='Shadow Blades · pre-pull'>" in html  # 90 s in the game data: framed
    assert "<li class='' title='Eviscerate · 0:01'>" in html and "<small>1</small>" in html
    assert html.endswith("<li class='then'>then your rotation</li></ol></section>")


def test_the_opener_keeps_only_what_the_action_list_presses(tmp_path):
    # issue #40 (a Frost Mage): Frozen Orb's and Flurry's bolts, scheduled like casts (75 frozen_orb_bolt for 3 orbs
    # in a SimC pull), read as dozens of orbs on a cooldown that does not allow it
    from collections import OrderedDict

    from paf import optimize

    log = tmp_path / "boss-pull.log"
    log.write_text("".join(f"{t:.3f} Player 'M' schedules execute for Action '{a}' ({sid})\n"
                           for t, a, sid in [(1.0, "frostbolt", 116), (3.3, "frozen_orb", 84714),
                                             (3.8, "frozen_orb_bolt", 84721), (4.3, "frozen_orb_bolt", 84721),
                                             (4.6, "flurry_bolt", 228354),
                                             (4.8, "use_item_treacherous_transmitter", 446209)]), encoding="utf-8")
    apl = OrderedDict({"": ["frostbolt", "frozen_orb,if=x", "use_item,name=treacherous_transmitter"]})
    assert optimize.apl_actions(apl) == {"frostbolt", "frozen_orb", "use_item"}
    got = [sid for _t, _a, sid in optimize.opener(log, actions=optimize.apl_actions(apl))]
    assert got == [116, 84714, 446209]


def test_a_cast_with_every_wave_is_the_wave_s_and_a_defensive_names_what_it_answers(monkeypatch):
    # Twin Fangs mythic (the owner's mockup pick): Rouse the Brood 1 s into every Spawn wave, no row of its own;
    # Feint for Ravenous Feast: Ravenous Feast a boss lane, "you: Feint"
    d = sheet(monkeypatch)
    d.waves = [(35.0, 3, 11.0, "Spawn of Vexhul"), (96.0, 3, 11.0, "Spawn of Vexhul")]
    d.actions = [Action("kill", "Spawn of Vexhul", "Kill the Spawn of Vexhul")]
    d.boss_casts = [("Rouse the Brood", [36.0, 97.0]), ("Ravenous Feast", [61.0, 122.0])]
    monkeypatch.setattr(fightview, "_defensives", lambda d: [(60.0, "Feint", "Ravenous Feast"),
                                                             (121.0, "Feint", "Ravenous Feast")])
    tl = fightview.timeline(d)
    assert [b.names for b in tl.boss] == [["Ravenous Feast"]] and tl.boss[0].sub == "you: Feint"
    assert [m.tip.splitlines()[1] for m in tl.boss[0].marks] == ["You answer with Feint (1 s before)"] * 2  # its own
    assert not any(x.name == "Rouse the Brood" for _t, x in tl.others)
    kill = next(lane for lane in tl.you if lane.kind == "kill")
    assert "Comes with Rouse the Brood (+1 s)" in kill.marks[0].tip
    monkeypatch.setattr(fightview, "_defensives", lambda d: [(60.0, "Feint", "Ravenous Feast")])  # one of two
    lane = fightview.timeline(d).boss[0]
    assert lane.sub == "you: Feint (1 of 2)" and [m.flag for m in lane.marks] == [False, True]
    assert lane.marks[1].tip.splitlines()[1] == "Your plan has no defensive for this one"
    feint = next(lane for lane in tl.you if lane.kind == "def")
    assert feint.sub == "for Ravenous Feast"
    assert "Feint each Ravenous Feast." in fightview.summary(d, tl)


def test_the_opener_says_the_shards_at_a_spender_what_is_up_and_the_burst_split(monkeypatch, tmp_path):
    # issue #41 (a Demonology tester): "how many shards at the Tyrant, must the dogs be out, what in the burst?"
    from paf import pulllog

    notes = pulllog.Notes("shards", {
        (4.794, 265187): pulllog.Press(4.794, "summon_demonic_tyrant", 265187, res=5, up=[104316]),
        (5.58, 105174): pulllog.Press(5.58, "hand_of_guldan", 105174, res=3, spends=True),
        (6.0, 686): pulllog.Press(6.0, "shadow_bolt", 686, res=1)},
        pulllog.Split(0.4, [(105174, "hand_of_guldan", 0.38)], [(264178, "demonbolt", 0.28)]),
        {104316: "Call Dreadstalkers", 105174: "Hand of Gul'dan", 264178: "Demonbolt"})
    d = sheet(monkeypatch)
    d.optimized[0].opener = [(4.794, "Summon Demonic Tyrant", 265187), (5.58, "Hand of Gul'dan", 105174),
                             (6.0, "Shadow Bolt", 686)]
    d.optimized[0].notes = notes
    monkeypatch.setattr("paf.gamedata.spell_cooldowns", lambda: {265187: (60.0, 1)})
    html = fightview.opener_html(d)
    assert "title='Summon Demonic Tyrant · 0:04 · 5 shards · with Call Dreadstalkers'" in html
    assert "<b class='res'>5</b><span class='up'>" in html
    assert "title='Hand of Gul&#x27;dan · 0:05 · 3 shards'" in html  # a spender: its shards
    assert "title='Shadow Bolt · 0:06'" in html  # a builder: none
    assert "In your cooldowns" in html and "38%" in html and "Between them" in html and "28%" in html
