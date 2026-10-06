import os

from paf import cache


def test_prune_removes_oldest_first(tmp_path):
    d = tmp_path / "sims" / "ab"
    d.mkdir(parents=True)
    for i in range(5):
        f = d / f"{i}.json"
        f.write_bytes(b"x" * 100)
        os.utime(f, (1000 + i, 1000 + i))
    freed = cache.prune(tmp_path / "sims", 250)
    assert freed == 300
    assert sorted(p.name for p in d.iterdir()) == ["3.json", "4.json"]


def test_sim_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    exe = tmp_path / "simc.exe"
    exe.write_bytes(b"bin")
    k1 = cache.sim_key(exe, "input", ["target_error=0.2"])
    assert k1 != cache.sim_key(exe, "input", ["target_error=0.1"])
    assert k1 != cache.sim_key(exe, "input2", ["target_error=0.2"])
    assert cache.sim_get(k1) is None
    src = tmp_path / "report.json"
    src.write_text("{}")
    cache.sim_put(k1, src)
    assert cache.sim_get(k1).read_text() == "{}"
    assert set(cache.prune_all(10 * 1024 * 1024)) == {"sims", "wcl", "runs"}


def test_prune_runs_keeps_the_newest(tmp_path):
    for i in range(8):
        d = tmp_path / f"run{i}"
        (d / "x").mkdir(parents=True)
        os.utime(d, (1000 + i, 1000 + i))
    cache.prune_runs(tmp_path, keep=3)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run5", "run6", "run7"]


def test_find_simc_takes_the_newest_install_and_drops_the_others(tmp_path, monkeypatch):
    from paf import simc_install

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.delenv("PAF_SIMC", raising=False)
    monkeypatch.setattr(simc_install.shutil, "which", lambda _: None)
    for name, t in (("1210.01.fff", 1000), ("1210.01.aaa", 2000)):
        exe = tmp_path / "simc" / name / "simc.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"x")
        os.utime(exe.parent, (t, t))
    assert simc_install.find_simc().parent.name == "1210.01.aaa"  # newest, though "fff" sorts after it
    assert simc_install.remove_old_simc() == 1
    assert [p.name for p in (tmp_path / "simc").iterdir()] == ["1210.01.aaa"]


def test_installed_copy_keeps_its_data_in_its_folder(tmp_path, monkeypatch):
    from paf import config

    app = tmp_path / "app"
    (app / "python").mkdir(parents=True)
    (app / config.INSTALL_MARKER).write_text("data")
    old = tmp_path / "home" / ".paf"
    (old / "reports").mkdir(parents=True)
    (old / ".env").write_text("WCL_CLIENT_ID=x\n")
    (old / "corpus-shaman-elemental.sqlite").write_bytes(b"db")
    (old / "simc" / "v1").mkdir(parents=True)
    monkeypatch.delenv("PAF_HOME", raising=False)
    monkeypatch.setattr(config.sys, "prefix", str(app / "python"))
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path / "home")
    config.installed_home.cache_clear()
    try:
        assert config.data_dir() == app / "data"
        assert set(config.migrate_old_home()) == {".env", "reports", "corpus-shaman-elemental.sqlite"}
        assert (app / "data" / ".env").is_file() and not old.exists()
    finally:
        config.installed_home.cache_clear()
