from paf import webtools


class Enc:
    id, name = 3492, "Ula'tek"


def test_every_command_has_a_form_but_the_app_ones():
    names = set(webtools.subparsers())
    listed = {n for _, ns in webtools.GROUPS for n in ns}
    assert names - listed == {"serve", "profile", "config", "raidqueue"}  # the app itself, home, settings, its queue
    page = webtools.tool_page("raidplan", [Enc()])
    assert "<select name='boss'>" in page and "name='swap_specs'" in page and "name='raid'" in page
    assert webtools.tool_page("serve", []) is None


def test_tool_args_from_a_form():
    form = {"boss": ["3492"], "difficulty": ["mythic"], "swap_specs": ["on"], "raid": [""], "options": [""]}
    assert webtools.tool_args("raidplan", form) == ["raidplan", "3492", "--difficulty", "mythic", "--swap-specs"]
    assert webtools.tool_args("nope", {}) is None


def test_settings_page(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.delenv("WCL_CLIENT_ID", raising=False)
    page = webtools.settings_page("Saved.")
    assert "cache_max_mb" in page and "SimulationCraft" in page and "Saved." in page


def test_settings_page_changes_the_warcraft_logs_key(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setenv("WCL_CLIENT_ID", "9a1b2c3d-long-client-id")
    page = webtools.settings_page()
    assert "9a1b2c3d…" in page and "long-client-id" not in page
    assert 'action="/credentials"' in page and 'name="back" value="settings"' in page
