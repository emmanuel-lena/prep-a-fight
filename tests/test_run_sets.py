from paf import simc


def test_run_sets_drops_a_profileset_simc_rejects(monkeypatch, tmp_path):
    calls = []

    def fake_run(text, run_dir, **kw):
        calls.append(text)
        if 'profileset."s1"' in text:
            raise simc.SimcError("simc failed (exit 82):\nError: Profileset 's1': Player 'X': Item 'crown' "
                                 "Slot 'head': Invalid type.\n")
        return "ok"

    monkeypatch.setattr(simc, "run", fake_run)
    logs = []
    out = simc.run_sets("warlock=X", [], {"s0": ["head=,id=1"], "s1": ["head=,id=2"]}, tmp_path, log=logs.append)
    assert out == "ok" and len(calls) == 2 and 'profileset."s0"' in calls[1]
    assert logs == ["  skipped: Player 'X': Item 'crown' Slot 'head': Invalid type."]
