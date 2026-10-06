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
