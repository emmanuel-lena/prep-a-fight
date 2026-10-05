from paf.profile import parse_simc_export, role, wcl_class_spec


def test_wcl_names_and_roles():
    dk = parse_simc_export('deathknight="X"\nspec=frost\nhead=,id=1\n')
    hunter = parse_simc_export('hunter="Y"\nspec=beast_mastery\nhead=,id=1\n')
    priest = parse_simc_export('priest="Z"\nspec=holy\nhead=,id=1\n')
    assert wcl_class_spec(dk) == ("DeathKnight", "Frost") and role(dk) == "damage"
    assert wcl_class_spec(hunter) == ("Hunter", "BeastMastery")
    assert role(priest) == "healer"


def test_profile_spec_drives_the_corpus(tmp_path, monkeypatch):
    from paf import settings
    from paf.corpus import db
    from paf.profile import use_profile_spec

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    (tmp_path / "corpus.sqlite").write_bytes(b"x")  # the corpus from before specs were separated
    assert db.db_path().name == "corpus-shaman-elemental.sqlite"  # renamed: it was the Elemental's
    assert (tmp_path / "corpus-shaman-elemental.sqlite").read_bytes() == b"x"
    use_profile_spec(parse_simc_export('warlock="P"\nspec=demonology\nhead=,id=1\n'))
    assert (settings.get("class"), settings.get("spec")) == ("Warlock", "Demonology")
    assert db.db_path().name == "corpus-warlock-demonology.sqlite"
