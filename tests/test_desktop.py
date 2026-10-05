from paf import desktop, simc_install


def test_the_icon_ships_with_the_package():
    assert desktop.ICON.is_file() and desktop.ICON.read_bytes()[:4] == b"\0\0\1\0"


def test_simc_status_is_quiet_until_the_app_starts_a_download(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setitem(simc_install._BACKGROUND, "thread", None)
    assert simc_install.simc_status() == ""
