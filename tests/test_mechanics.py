from paf.mechanics import Section, clean_text, dedupe


def test_clean_text():
    raw = ("$bullet; |cFF2959D3|Hspell:1299960|h[Toxic Deluge]|h|r creates venom. "
           "$[!16 On Mythic difficulty, it mutates.$]")
    assert clean_text(raw) == "- Toxic Deluge creates venom. On Mythic difficulty, it mutates."
    assert clean_text(raw, mythic=False) == "- Toxic Deluge creates venom."


def sec(title, spell, flags=(), mask=-1, text=""):
    return Section(0, title, "ability", spell, list(flags), text, 0, 0, mask)


def test_dedupe_keeps_most_specific_and_filters_difficulty():
    secs = [sec("Venom", 1), sec("Venom", 1, ["mythic"], 0, "mythic text"), sec("Axe", 2, ["mythic"])]
    heroic = dedupe(secs, "heroic")
    assert [s.title for s in heroic] == ["Venom"] and heroic[0].text == ""
    mythic = dedupe(secs, "mythic")
    assert [(s.title, s.text) for s in mythic] == [("Venom", "mythic text"), ("Axe", "")]
