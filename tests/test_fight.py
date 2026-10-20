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


def test_adds_alive_when_the_boss_comes_back_are_split():
    f = Fight("B", 400, add_waves=[AddWave(148, 1, 114, "Echo", scalable=False), AddWave(10, 3, 20, "Amani"),
                                   AddWave(140, 2, 140, "Before"), AddWave(250, 2, 30, "During")],
              invulnerable=[Window(158.7, 103)])
    events = [e for e in f.raid_event_lines() if "adds" in e]
    assert "first=10,duration=20" in events[0]  # untouched
    # spawned before the immunity and outliving it: dies 1 s before the boss comes back at 261.7, back right after
    assert "first=140,duration=120.7" in events[1] and "first=262.2,duration=17.8" in events[2]
    assert "first=148,duration=112.7" in events[3]  # dies 1 s before the boss comes back; 0.3 s left: gone
    assert "first=250,duration=10.7" in events[4]  # an intermission's add dies with the intermission: no respawn
    assert len(events) == 5


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


def test_overlapping_movement_is_merged():
    from paf.fight import merged_movement

    out = merged_movement([Window(165, 13), Window(176, 1), Window(189, 3), Window(300, 5, distance=20)])
    assert [(w.start, w.duration, w.distance) for w in out] == [(165, 13, 0), (189, 3, 0), (300, 5, 20)]
    out = merged_movement([Window(10, 5), Window(12, 8)])
    assert [(w.start, w.duration) for w in out] == [(10, 10)]


def test_unique_units_are_not_scaled():
    f = Fight("B", 100, add_waves=[AddWave(10, 4, 20), AddWave(50, 1, 20, "Heart", scalable=False)], add_scale=2.0)
    events = [e for e in f.to_simc() if "adds" in e]
    assert "count=8" in events[0] and "count=1" in events[1]


def test_an_intermission_add_dies_with_the_intermission():
    from paf.fight import AddWave, Fight, Window

    f = Fight("B", 240, add_waves=[AddWave(102.6, 1, 89.9, "Echo", scalable=False), AddWave(52.7, 6, 16.7, "Amani")],
              invulnerable=[Window(97.3, 54.8)])
    echo, amani = f.add_waves
    assert echo.lifetime == 49.5 and amani.lifetime == 16.7  # cut at the immunity's end; the earlier wave untouched
    assert not any(a > 152.1 for a, _d, w in f._spawns() if w.name == "Echo")  # no respawn in Stage Two


def test_no_add_is_up_when_the_boss_comes_back():
    """SimC never goes back to the boss when an add outlives an immunity (retarget=1). The Sentinels' Venom
    Coagulation at 55.9 s, 0.8 s before the end of Vitriolic Stasis, kept the whole fight on the adds (0.33 of the
    top players' DPS)."""
    from paf.fight import AddWave, Fight, Window

    f = Fight("B", 280, add_waves=[AddWave(55.9, 1, 1, "Venom Coagulation"), AddWave(0, 1, 50.9, "Blood"),
                                   AddWave(40, 1, 30, "Blood")],
              invulnerable=[Window(46.2, 10.5)])
    back = 56.7
    assert not any(a < back <= a + d for a, d, _w in f._spawns())
    assert any(a == back + 0.5 for a, _d, w in f._spawns() if w.time == 40)  # it comes back after


def test_a_wave_logged_at_an_immunitys_end_belongs_to_the_next_phase():
    """The slower Nek'zali heroic kills: 18 Restless Amani logged 0.8 s before Stage Two were cut to nothing."""
    from paf.fight import AddWave, Fight, Window

    f = Fight("B", 314, add_waves=[AddWave(202.6, 18, 20.0, "Restless Amani"), AddWave(130, 1, 90, "Echo")],
              invulnerable=[Window(126.4, 77.0)])
    amani, echo = f.add_waves
    assert (amani.time, amani.lifetime) == (203.9, 20.0)
    assert echo.lifetime == 73.4  # an intermission's add still dies with it
    assert any(w.name == "Restless Amani" and d == 20.0 for _a, d, w in f._spawns())
