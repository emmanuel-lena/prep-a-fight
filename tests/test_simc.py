import json

import pytest

from paf.simc import build_input, fmt, parse_json


def test_fmt_is_locale_independent():
    assert fmt(0.1) == "0.1"
    assert fmt(300) == "300"
    assert fmt(2.0) == "2"


def test_build_input_orders_profile_fight_profilesets():
    text = build_input('shaman="X"\nspec=elemental', ["fight_style=Patchwerk", "max_time=300"],
                       {"alt 1": ["talents=AAA", "trinket1=,id=1"]})
    lines = text.splitlines()
    assert lines[0] == 'shaman="X"'
    assert lines.index("max_time=300") < lines.index('profileset."alt 1"=talents=AAA')
    assert lines[-1] == 'profileset."alt 1"+=trinket1=,id=1'


def test_build_input_rejects_dotted_names():
    with pytest.raises(ValueError):
        build_input("x", None, {"a.b": ["talents=1"]})


def test_parse_json(tmp_path):
    data = {"sim": {
        "players": [{"collected_data": {
            "dps": {"mean": 1000.0, "mean_std_dev": 5.0},
            "prioritydps": {"mean": 800.0, "mean_std_dev": 4.0},
        }}],
        "profilesets": {"metric": "Damage per Second", "results": [
            {"name": "a", "mean": 1010.0, "mean_error": 6.0, "iterations": 100,
             "additional_metrics": [{"metric": "prioritydps", "mean": 790.0, "mean_error": 3.0}]},
        ]},
    }}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(data))
    r = parse_json(p)
    assert r.baseline["dps"].mean == 1000.0
    assert r.baseline["prioritydps"].mean == 800.0
    ps = r.profilesets[0]
    assert ps.dps.mean == 1010.0 and ps.dps.error == 6.0
    assert ps.metrics["prioritydps"].mean == 790.0
    assert r.delta_pct(ps) == pytest.approx(1.0)
