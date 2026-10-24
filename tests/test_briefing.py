from types import SimpleNamespace

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


def test_what_to_aim_for_comes_first_in_the_overview():
    d = SimpleNamespace(sim_dps=250000.0, sim_boss_dps=180000.0, patchwerk_dps=300000.0, spec="Subtlety",
                        your_profile=SimpleNamespace(dps=290000.0, boss_dps=231000.0))
    html = briefing.aim_html(d)
    assert "You can aim for" in html and "180k" in html and "250k in all" in html
    assert "On a training dummy" in html and "this fight costs you 17%" in html
    assert "The best Subtlety" in html and "290k" in html  # the total: WCL's boss metric counts other units
    assert briefing.aim_html(SimpleNamespace(sim_dps=None)) == ""
    alone = briefing.aim_html(SimpleNamespace(sim_dps=200000.0, sim_boss_dps=None, patchwerk_dps=None, spec="Arms",
                                              your_profile=None))
    assert "200k" in alone and "The best" not in alone


def test_your_character_in_each_spec_shows_as_tiles_for_your_role():
    rows = [{"spec": "Subtlety", "label": "Subtlety", "sim": 100.0, "error": 0.1},
            {"spec": "Outlaw", "label": "Outlaw", "sim": 106.0, "error": 0.1},
            {"spec": "Assassination", "label": "Assassination", "sim": 99.9, "error": 0.1}]
    d = SimpleNamespace(specs={"verdict": "go", "mine": "Subtlety", "role": "boss", "assigns": 1, "rows": rows})
    html = briefing.spec_html(d)
    assert "We simmed your character in each damage spec of your class" in html
    assert "for boss damage, with your 1 assignment, on this fight" in html
    assert "<div class='spt mine'><span class='spt-n'>Subtlety</span><span class='spt-v'>your spec</span>" in html
    assert "<div class='spt go'><span class='spt-n'>Outlaw</span><span class='spt-v'>+6%</span>" in html
    assert "<div class='spt same'><span class='spt-n'>Assassination</span><span class='spt-v'>same</span>" in html
    assert briefing.spec_html(SimpleNamespace(specs=None)) == ""


def test_a_spec_simmed_one_item_short_is_marked_and_said_once():
    # DPS confirm round 6: "simmed without Band of the Swarmcaller (too new for SimC)" on two tiles
    s = {"mine": "Subtlety", "verdict": "stay", "notes": [
        "Subtlety: the top players' finger2 is unknown to this SimC build; simmed with that slot empty.",
        "Assassination: the top players' finger2 is unknown to this SimC build; simmed with that slot empty."],
         "rows": [{"spec": s_, "label": s_, "sim": v, "error": 0.2,
                   "items": [{"slot": "finger2", "name": "Band of the Swarmcaller"}]}
                  for s_, v in (("Subtlety", 100.0), ("Assassination", 79.0), ("Outlaw", 94.0))]}
    out = briefing.spec_html(SimpleNamespace(specs=s))
    assert out.count("&dagger;") == 0 and out.count("Band of the Swarmcaller") == 1  # no dagger: the note says
    assert "Every gap is only roughly right: Subtlety and Assassination" in out  # yours short, every gap rough


def test_the_lede_names_a_boss_unit_beside_the_add_waves():
    """Fresh DPS review: "2 waves of adds" on a fight whose timeline draws 3 (the Echo of Jawae left out)."""
    from paf.fight import AddWave, Fight

    d = PrepData("Nek'zali", "heroic", "Elemental", "X", duration=255)
    d.fight = Fight("x", 255, add_waves=[AddWave(52, 6, 18, "Restless Amani"), AddWave(73, 1, 75, "Echo of Jawae",
                                                                                      scalable=False),
                                         AddWave(167, 14, 18, "Restless Amani")])
    d.waves = [(52, 6, 18, "Restless Amani"), (73, 1, 75, "Echo of Jawae"), (167, 14, 18, "Restless Amani")]
    assert "with 2 waves of adds and Echo of Jawae" in briefing.lede_html(d)
