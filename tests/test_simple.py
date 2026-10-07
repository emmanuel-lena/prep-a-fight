import re

from paf import simple
from paf.fight import Fight
from paf.optimize import Plan, Rule
from paf.prep_report import PrepData, render


def sheet():
    d = PrepData("Boss", "heroic", "Elemental", "Char", kills=40, duration=300)
    d.phases = [("Stage One", 0.0), ("Stage Two", 150.0)]
    d.fight = Fight("B", 300)
    d.cd_names = {"ascendance": "Ascendance", "stormkeeper": "Stormkeeper"}
    d.icons = {"Ascendance": "spell_fire_elementaldevastation"}
    p = Plan("boss", {"ascendance": Rule("hold_vulnerable_60", "", None), "stormkeeper": Rule("default", "", None)},
             4.0, 0.2)
    d.optimized = [p]
    return d


def test_simple_view_comes_first_with_three_questions(monkeypatch):
    d = sheet()
    monkeypatch.setattr("paf.optimize.plan_moments",
                        lambda plan, fight, names: [(20, ["Ascendance"]), (80, ["Stormkeeper"]), (200, ["Ascendance"])])
    page = render(d)
    assert page.index('id="simple"') < page.index('id="overview"')  # shown by default
    view = simple.simple_html(d)
    assert "Your cooldowns" in view and "Hold them for these moments." in view
    assert re.search(r"<b>Ascendance</b><span class='times'><time>0:20</time><time>3:20</time>", view)
    assert "Nothing to change" in view  # no talents nor gear worth it
    assert "See all the details" in view
    assert "&larr; Simple view" in page  # the way back from the details
    assert "{" not in view


def test_vertical_fight_boss_left_you_right(monkeypatch):
    from paf.actions import Action

    d = sheet()
    d.boss_casts = [("Soul Transfer", [21.0, 160.0])]
    d.waves = [(50.0, 4, 20.0, "Amani")]
    d.actions = [Action("kill", "Amani", "Kill the Amani (~4 per kill)")]
    monkeypatch.setattr("paf.optimize.plan_moments", lambda plan, fight, names: [(20, ["Ascendance"])])
    view = simple.fight_html(d)
    phases = view.split("<details")[1:]
    assert len(phases) == 2 and " open>" in phases[0] and " open>" not in phases[1]  # the first phase is open
    first = phases[0]
    # one row at 0:20: the boss's spell on the left, your cooldown on the right
    assert re.search(r"<div class='l'>.*Soul Transfer.*</div><time>0:20</time><div class='r'>.*Ascendance", first)
    assert "4 × Amani" in first and "Kill them" in first and "inv_misc_groupneedmore" in first
    assert "<time>2:40</time>" in phases[1]


def test_simple_view_in_french(monkeypatch):
    from paf.i18n import translate

    d = sheet()
    monkeypatch.setattr("paf.optimize.plan_moments", lambda plan, fight, names: [(20, ["Ascendance"])])
    monkeypatch.setenv("PAF_LANG", "fr")
    page = translate(simple.simple_html(d))
    assert "Tes CD" in page and "Garde-les pour ces moments." in page and "Rien à changer" in page
    assert "Le combat, pas à pas" in page and "À gauche : ce que fait le boss." in page
