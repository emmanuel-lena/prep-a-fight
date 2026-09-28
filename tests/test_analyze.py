from paf.corpus.analyze import canonical_waves, fight_waves


def test_fight_waves_groups_close_spawns():
    spawns = [(28, 14, "A"), (31, 12, "A"), (122, 19, "A"), (126, 15, "B"), (187, 12, "A")]
    waves = fight_waves(spawns)
    assert [(w[0], w[1]) for w in waves] == [(28, 2), (122, 2), (187, 1)]
    assert waves[1][3] == ["A", "B"]


def test_canonical_waves_keeps_recurring_waves_only():
    k1 = fight_waves([(28, 14, "A"), (30, 14, "A"), (122, 19, "A")])
    k2 = fight_waves([(27, 16, "A"), (124, 17, "A"), (400, 10, "C")])  # 400 s wave only in one kill of three
    k3 = fight_waves([(29, 15, "A"), (123, 18, "A")])
    waves = canonical_waves([k1, k2, k3])
    assert [w.t for w in waves] == [28.0, 123.0]
    assert waves[0].support == 1.0
    assert waves[0].count == 1  # median count across kills (2, 1, 1)
