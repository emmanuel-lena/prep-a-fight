from paf.export import fight_lines
from paf.fight import AddWave, Fight
from paf.prep_report import PrepData, export_html


def test_fight_export_for_raidbots():
    fight = Fight(name="Boss", duration=300, add_waves=[AddWave(30, 3, 20)], lust_time=5)
    text = fight_lines("Boss mythic", fight, "boss damage", ["actions=/lava_burst"])
    assert "fight_style" not in text.replace("# Do not add a fight style: fight_style=Patchwerk", "")
    assert "max_time=300" in text and "raid_events=/adds" in text and text.rstrip().endswith("actions=/lava_burst")
    d = PrepData(boss="Boss", difficulty="mythic", spec="Elemental", character="X")
    d.export = {"": text}
    assert "raidbots.com/simbot/advanced" in export_html(d) and "Copy the fight" in export_html(d)
