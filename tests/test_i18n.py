from paf import i18n


def test_french_page(monkeypatch, tmp_path):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))  # no table of game names: only the app's catalog
    html = ("<h1>Your prepared bosses</h1><p>Time Warp</p><td>Time</td><p>Kill the Restless Amani (~36 per kill): "
            "the top raids kill them in ~19 s.</p><p>the top players&#x27; real DPS</p>"
            "<script>var x='Your prepared bosses'</script><input placeholder=\"Your message\">"
            "<pre>Home</pre>")
    fr = i18n.translate(html, "fr")
    assert "<h1>Tes boss préparés</h1>" in fr
    assert "<p>Time Warp</p>" in fr and "<td>Temps</td>" in fr  # one word: only a whole text
    assert "Tuer : Restless Amani (~36 par kill) : les meilleurs raids les tuent en ~19 s." in fr
    assert "var x='Your prepared bosses'" in fr and "<pre>Home</pre>" in fr  # scripts and code left alone
    assert 'placeholder="Ton message"' in fr
    assert i18n.translate(html, "en") == html
    assert i18n.untranslated("<p>Something new here</p><p>Your prepared bosses</p>", "fr") == ["Something new here"]


def test_languages(monkeypatch):
    monkeypatch.delenv("PAF_LANG")
    assert i18n.available()["fr"] == "Français" and i18n.available()["en"] == "English"
    monkeypatch.setattr(i18n.settings, "get", lambda k: "fr")
    assert i18n.language() == "fr" and i18n.wow_locale() == "frFR"
    monkeypatch.setattr(i18n.settings, "get", lambda k: "auto")
    monkeypatch.setattr(i18n, "system_language", lambda: "de")  # no German catalog yet: English
    assert i18n.language() == "en"
    monkeypatch.setattr(i18n, "system_language", lambda: "fr")
    assert i18n.language() == "fr"


def test_a_textarea_placeholder_is_translated_not_its_content(monkeypatch):
    monkeypatch.setenv("PAF_LANG", "fr")
    box = '<textarea placeholder="Paste the /simc export here">Paste the /simc export here</textarea>'
    out = i18n.translate(box, "fr")
    assert 'placeholder="Colle l&#x27;export /simc ici"' in out
    assert out.endswith(">Paste the /simc export here</textarea>")  # the content is the player's
