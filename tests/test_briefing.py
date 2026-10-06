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
