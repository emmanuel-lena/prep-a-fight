import json
import time

from paf import update, web


def _rel(tag, draft=False, asset=True):
    assets = [{"name": f"prep-a-fight-setup-{tag[1:]}.exe", "size": 3, "digest": "sha256:abc",
               "browser_download_url": f"https://github.com/x/y/releases/download/{tag}/setup.exe"}] if asset else []
    return {"tag_name": tag, "draft": draft, "html_url": f"https://github.com/x/y/releases/tag/{tag}", "body": "notes",
            "assets": assets}


def test_newest_release_with_an_installer():
    assert update.parse_version("v0.1.10") > update.parse_version("0.1.9")
    rel = update.parse_releases([_rel("v0.1.6"), _rel("v0.2.0", draft=True), _rel("v0.1.10"),
                                 _rel("v0.3.0", asset=False)])
    assert rel.version == "0.1.10" and rel.sha256 == "abc" and rel.size == 3


def test_available_uses_the_daily_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "update.json").write_text(json.dumps({"at": time.time(), "releases": [_rel("v99.0.0")]}))
    monkeypatch.setattr(update, "_get", lambda url: (_ for _ in ()).throw(AssertionError("no network")))
    assert update.available().version == "99.0.0"
    (tmp_path / "web" / "update.json").write_text(json.dumps({"at": time.time(), "releases": [_rel("v0.0.1")]}))
    assert update.available() is None  # older than this version


def test_banner_and_no_update_during_a_prep(monkeypatch):
    rel = update.parse_releases([_rel("v99.0.0")])
    monkeypatch.setitem(update.STATE, "release", rel)
    monkeypatch.setattr(update, "install_dir", lambda: None)
    assert "Version 99.0.0 is out" in web.update_banner() and "Download it" in web.update_banner()
    monkeypatch.setattr(update, "install_dir", lambda: "C:/app")
    assert "Update now" in web.update_banner()
    monkeypatch.setitem(web.JOBS.jobs, "j1", {"status": "running"})
    assert "A prep is running" in web.run_update()
    monkeypatch.setitem(update.STATE, "release", None)
    assert web.update_banner() == ""


def test_a_release_with_another_versions_installer_is_ignored():
    # 0.5.3 once held 0.5.2's installer next to its own: only the installer named after the release counts
    rel = _rel("v0.5.3")
    rel["assets"].insert(0, {"name": "prep-a-fight-setup-0.5.2.exe", "size": 9, "digest": "sha256:old",
                             "browser_download_url": "https://github.com/x/y/releases/download/v0.5.3/old.exe"})
    assert update.parse_releases([rel]).sha256 == "abc"
    only_old = _rel("v0.5.4")
    only_old["assets"][0]["name"] = "prep-a-fight-setup-0.5.2.exe"
    assert update.parse_releases([only_old]) is None


def test_the_app_knows_its_own_version():
    # the updater compares __version__ with the releases: it must follow pyproject.toml (it once stayed at 0.3.1)
    import tomllib
    from pathlib import Path

    import paf

    project = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert paf.__version__ == project["project"]["version"]
