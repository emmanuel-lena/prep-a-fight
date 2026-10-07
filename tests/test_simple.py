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
    assert view.count("class='mk up'") == 3 and "See all the details" in view
    assert "&larr; Simple view" in page  # the way back from the details
    assert "{" not in view


def test_markers_never_overlap():
    rows = simple._rows([0, 1, 2, 100, 101], 300)
    assert rows[:3] == [0, 1, 2] and rows[3] == 0 and rows[4] == 1


def test_simple_view_in_french(monkeypatch):
    from paf.i18n import translate

    d = sheet()
    monkeypatch.setattr("paf.optimize.plan_moments", lambda plan, fight, names: [(20, ["Ascendance"])])
    monkeypatch.setenv("PAF_LANG", "fr")
    page = translate(simple.simple_html(d))
    assert "Tes CD" in page and "Garde-les pour ces moments." in page and "Rien à changer" in page
    assert "data-text='lance Ascendance'" in page or 'data-text="lance Ascendance"' in page
