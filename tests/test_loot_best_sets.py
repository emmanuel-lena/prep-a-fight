from pathlib import Path

from paf import droptimizer, simc
from paf.droptimizer import LootItem, loot_in_best_sets
from paf.profile import parse_simc_export
from paf.topgear import FightProfile


def test_loot_in_best_sets_builds_sets_and_takes_best_minus_best(monkeypatch):
    prof = parse_simc_export('shaman="T"\ntrinket1=,id=1\ntrinket2=,id=2\nhead=,id=3\n')
    items = [LootItem(10, "Trinket", "trinket", "Boss")]
    seen = {}

    def fake_run(text, run_dir, **kw):
        sets = {}
        for line in text.splitlines():
            if line.startswith('profileset."'):
                name = line.split('"')[1]
                sets.setdefault(name, []).append(line.split("=", 1)[1].lstrip("=").lstrip("+"))
        seen.update(sets)
        # base set b1 (+2%), item alone on equipped (+1%), item in b1 (+2.5%)
        values = {"b1": 2.0, "b0_i0_0": 1.0, "b0_i0_1": 0.5, "b1_i0_0": 2.5, "b1_i0_1": 1.0}
        res = simc.SimResult({"dps": simc.Metric(100.0, 0.1)}, [], Path("x"))
        res.profilesets = [simc.ProfilesetResult(n, {"dps": simc.Metric(100.0 * (1 + v / 100), 0.1)})
                           for n, v in values.items()]
        return res

    monkeypatch.setattr(droptimizer.simc, "run", fake_run)
    real = loot_in_best_sets("profile", prof, items, [[], ["head=,id=99"]], FightProfile("f", ["x=1"]), Path("r"), 320)
    assert round(real[10], 6) == 0.5  # best with the item (2.5) minus best without it (2.0)
    assert any("head=,id=99" in line for line in seen["b1_i0_0"])  # the base set is kept around the item
