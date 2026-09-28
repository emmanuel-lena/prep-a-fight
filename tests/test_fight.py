from paf.fight import AddWave, Fight, Window


def example():
    return Fight(
        name="Test boss", duration=340,
        add_waves=[AddWave(170, 3, 25), AddWave(65, 3, 22), AddWave(270, 5, 18)],
        invulnerable=[Window(150, 12)],
        movement=[Window(120, 6)],
        lust_time=0, power_infusion=[10, 130, 250],
    )


def test_to_simc():
    lines = example().to_simc()
    assert "fixed_time=1" in lines and "max_time=340" in lines
    assert not any(line.startswith("fight_style") for line in lines)
    assert "external_buffs.power_infusion=10/130/250" in lines
    events = [x for x in lines if x.startswith("raid_events")]
    assert events[0] == "raid_events=/adds,name=wave1,count=3,first=65,duration=22,cooldown=9999"
    assert all(e.startswith("raid_events+=/") for e in events[1:])
    assert any("invulnerable,first=150,duration=12" in e for e in events)
    assert any("movement,first=120,cooldown=9999,duration=6" in e for e in events)


def test_no_lust():
    f = example()
    f.lust_time = None
    assert "override.bloodlust=0" in f.to_simc()


def test_save_load_roundtrip(tmp_path):
    f = example()
    f.save(tmp_path / "boss.json")
    g = Fight.load(tmp_path / "boss.json")
    assert g == f
    assert (tmp_path / "boss.simc").read_text().startswith("# fight: Test boss")
