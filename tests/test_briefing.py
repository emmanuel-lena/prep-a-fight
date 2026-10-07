from paf import briefing
from paf.prep_report import PrepData


def test_lede_says_the_fight_in_one_sentence():
    d = PrepData("Boss", "mythic", "Assassination", "X", duration=379)
    d.waves = [(50, 4, 20, "Amani"), (120, 18, 15, "Amani"), (200, 0, 10, "Heart: boss takes x2 damage")]
    d.lust, d.add_share_spec = 2, 0.12
    lede = briefing.lede_html(d)
    assert "A 6:19 fight with 2 waves of adds, with Bloodlust at the pull." in lede
    assert "keep 88% of their damage on the boss and put 12% on the adds" in lede


def test_timeline_labels_never_overlap():
    events = [(10, "Vanish", True), (12, "Potion", False), (14, "Deathmark + Kingsbane", True), (300, "Feint", True),
              (360, "Vanish", True)]
    rows = briefing._rows(events, 379)
    assert rows[0] != rows[1] != rows[2] and rows[0] != rows[2]  # three labels at the same moment: three rows
    assert rows[3] == 0  # far away: back to the first row (and past FLIP_AT it opens leftwards)


def test_lede_of_a_council_in_french(monkeypatch):
    from paf.fight import Fight, Focus
    from paf.i18n import translate

    d = PrepData("The Explorers", "mythic", "Elemental", "X", duration=294)
    d.lust, d.add_share_spec = 0.5, 0.01
    d.fight = Fight("x", 294, focus=[Focus(0, 70, "Trader", 0.6), Focus(70, 224, "Sage", 0.5)], targets=2)
    lede = briefing.lede_html(d)
    assert "A council of 2 bosses, 2 of them stacked: the top players cleave them and start on Trader." in lede
    assert "stay on the boss" not in lede
    monkeypatch.setenv("PAF_LANG", "fr")
    assert "Un conseil de 2 boss, dont 2 packés : les tops les cleavent et commencent par Trader." in translate(lede)
