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
    assert set(cache.prune_all(10 * 1024 * 1024)) == {"sims", "wcl"}
