"""Integration tests against the real simc binary (run with: pytest -m simc)."""

import pytest

from paf import simc
from paf.simc_install import bundled_profile, find_simc

pytestmark = pytest.mark.simc


@pytest.fixture(scope="module")
def profile_text():
    if find_simc() is None:
        pytest.skip("simc not installed")
    p = bundled_profile()
    if p is None:
        pytest.skip("no bundled Elemental profile")
    return p.read_text(encoding="utf-8")


def test_baseline_and_profileset(profile_text, tmp_path):
    text = simc.build_input(profile_text, ["fight_style=Patchwerk", "max_time=120"],
                            {"no_trinket1": ["trinket1="]})
    r = simc.run(text, tmp_path, target_error=1.0, threads=8)
    assert r.baseline["dps"].mean > 0
    assert len(r.profilesets) == 1
    assert r.delta_pct(r.profilesets[0]) < 0  # removing a trinket must lose dps
