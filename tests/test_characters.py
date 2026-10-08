from paf import characters, settings

SHAMAN = 'shaman="Ixuu"\nspec=elemental\nhead=,id=1\n'
ROGUE = 'rogue="Stab"\nspec=assassination\nhead=,id=2\n### Gear from Bags\n#\n# Ring (300)\n# finger1=,id=3\n'


def test_one_export_per_character_and_a_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    characters.save(SHAMAN)
    rogue = characters.save(ROGUE)
    assert rogue.current and rogue.bags == 1 and settings.get("spec") == "Assassination"
    assert [c.name for c in characters.all_characters()] == ["Stab", "Ixuu"]  # the active one first
    assert characters.select("ixuu-shaman") and settings.get("spec") == "Elemental"
    assert (tmp_path / "profiles" / "current.simc").read_text(encoding="utf-8").startswith('shaman="Ixuu"')
    characters.save(SHAMAN.replace("id=1", "id=9"))  # the same character again: updated, not doubled
    assert len(characters.all_characters()) == 2
    assert "id=9" in (tmp_path / "profiles" / "chars" / "ixuu-shaman.simc").read_text(encoding="utf-8")
    assert characters.remove("ixuu-shaman") and characters.current_slug() == "stab-rogue"
    assert not characters.select("../evil")


def test_a_profile_loaded_before_becomes_the_first_character(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "current.simc").write_text(SHAMAN, encoding="utf-8")
    assert [c.slug for c in characters.all_characters()] == ["ixuu-shaman"]


def test_an_imported_character_is_marked(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    c = characters.save(SHAMAN, imported=True)
    assert c.imported and characters.is_imported((tmp_path / "profiles" / "current.simc").read_text(encoding="utf-8"))


def test_characters_page_and_the_add_button(tmp_path, monkeypatch):
    from paf import web

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    characters.save(SHAMAN)
    characters.save(ROGUE)
    page = web.characters_page()
    assert page.count("class=\"ccard") == 2 and "Play this character" in page and "id='add'" in page
    assert 'action="/profile"' in page and 'action="/character/remove"' in page
    # removing asks first: the remove form sits inside a folded confirmation
    assert page.count('<details class="rm">') == 2 and "Yes, remove it" in page and "Keep it" in page
    assert 'href="/characters#add"' in web.characters_strip()
    assert 'href="/characters"' in web.page("X", "").decode()  # in the top bar
