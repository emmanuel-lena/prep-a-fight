from paf import i18n, names
from paf.mechanics import Section


def _section(sid, title, text, kind="ability"):
    return Section(sid, title, kind, 0, [], text, 0, sid, -1)


def test_journal_and_spell_names_in_french(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    en = [_section(1, "Soul Transfer", "Echoes awaken. - Kill them. - Then run."),
          _section(2, "Immortal Coil", "Hits everyone.")]
    fr = [_section(1, "Transfert d'âme", "Les échos s'éveillent. - Tuez-les. - Puis courez."),
          _section(2, "Section\xa079", "Touche tout le monde.")]
    monkeypatch.setattr("paf.mechanics.encounter_sections", lambda enc, locale="": fr if locale else en)
    boss = {"": "Nek'zali the Soulcoiler", "frFR": "Nek’zali l’Entortillâme"}
    monkeypatch.setattr("paf.gamedata.table_rows", lambda table, locale="", **kw: [
        {"DungeonEncounterID": "3470", "Name_lang": boss[locale]}])
    monkeypatch.setattr(names, "_tooltip_name", lambda ref, locale: {"spell=31224": "Cape d'ombre"}.get(ref, ""))
    names.build(3470, "mythic", {"Cloak of Shadows": "spell=31224", "use_item:trinket1": "item=1"}, "frFR")
    m = names.mapping("frFR")
    assert m["Soul Transfer"] == "Transfert d'âme" and m["Kill them."] == "Tuez-les."
    assert "Immortal Coil" not in m  # a placeholder title is never used
    assert m["Nek'zali the Soulcoiler"] == "Nek’zali l’Entortillâme" and m["Cloak of Shadows"] == "Cape d'ombre"
    assert "use_item:trinket1" not in m
    page = "<h1>Nek&#x27;zali the Soulcoiler</h1><a>Cloak of Shadows</a><li>Kill them.</li><td>Feint</td>"
    fr_page = i18n.translate(page, "fr")
    assert "Nek’zali l’Entortillâme" in fr_page and "Cape d&#x27;ombre" in fr_page and "Tuez-les." in fr_page
    assert "<td>Feint</td>" in fr_page  # not in the table: stays in English


def test_spell_descriptions_and_long_texts_are_paired(tmp_path, monkeypatch):
    from paf import bossguide

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    no_text = Section(5, "Serpent Flame", "ability", 777, [], "", 0, 5, -1)  # the page shows the spell's description
    sections = {"": [no_text], "frFR": [Section(5, "Flamme serpentine", "ability", 777, [], "", 0, 5, -1)]}
    descriptions = {"": "A flame slithers.", "frFR": "Une flamme rampe."}
    monkeypatch.setattr("paf.mechanics.encounter_sections", lambda enc, locale="": sections[locale])
    monkeypatch.setattr("paf.gamedata.table_rows", lambda table, locale="", **kw: [])
    monkeypatch.setattr(bossguide, "describe", lambda sid, locale="": descriptions[locale])
    names.build(3497, "mythic", {}, "frFR")
    assert names.mapping("frFR")["A flame slithers."] == "Une flamme rampe."
    assert names.load("frFR")["journals"] == ["3497"]  # built once per boss
    long = "A fish found within one of Trader Gebbo's boxes. " * 5
    unit = Section(1, "Unit", "creature", 0, [], long, 9, 1, -1)
    html = bossguide.abilities_html([Section(9, "Stage One", "stage", 0, [], "", 0, 0, -1, [unit])])
    assert bossguide.e(long) in html  # whole, never cut: the translation matches whole texts
