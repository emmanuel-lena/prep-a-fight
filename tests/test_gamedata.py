from paf import gamedata


def test_damage_taken_amp_prefers_the_difficulty_row(monkeypatch):
    rows = [
        {"EffectAura": "87", "DifficultyID": "220", "EffectBasePointsF": "200"},  # story mode
        {"EffectAura": "87", "DifficultyID": "0", "EffectBasePointsF": "100"},    # default
        {"EffectAura": "3", "DifficultyID": "0", "EffectBasePointsF": "999"},     # another effect
    ]
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda table, col, value: rows)
    assert gamedata.damage_taken_amp(1299526, "heroic") == 2.0
    rows.append({"EffectAura": "87", "DifficultyID": "16", "EffectBasePointsF": "150"})
    assert gamedata.damage_taken_amp(1299526, "mythic") == 2.5


def test_damage_taken_amp_none_without_the_aura(monkeypatch):
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda table, col, value: [])
    assert gamedata.damage_taken_amp(1, "heroic") is None


def test_known_not_amp_follows_the_triggered_spells(monkeypatch):
    from paf import gamedata

    effects = {1: [{"EffectAura": "226", "EffectTriggerSpell": "0"}],  # a periodic dummy: known, no amp
               2: [{"EffectAura": "23", "EffectTriggerSpell": "3"}],  # triggers spell 3, which is an amp
               3: [{"EffectAura": "87", "EffectTriggerSpell": "0", "EffectBasePointsF": "30"}]}
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda table, col, sid, locale="": effects.get(sid, []))
    assert gamedata.known_not_amp(1)
    assert not gamedata.known_not_amp(2)
    assert not gamedata.known_not_amp(3)
    assert not gamedata.known_not_amp(9)  # unknown to the game data: the logs may still be right


def test_a_charge_longer_than_the_spells_own_cooldown_wins(monkeypatch):
    """Shield Wall: one charge of 180 s and an 8 s lockout; read as 8 s it fell out of the tank sheet's defensives."""
    tables = {"SpellCategory": [{"ID": "1929", "ChargeRecoveryTime": "180000", "MaxCharges": "1"}],
              "SpellCategories": [{"SpellID": "871", "ChargeCategory": "1929"}],
              "SpellCooldowns": [{"SpellID": "871", "RecoveryTime": "8000", "CategoryRecoveryTime": "0",
                                  "DifficultyID": "0"},
                                 {"SpellID": "12975", "RecoveryTime": "180000", "CategoryRecoveryTime": "20000",
                                  "DifficultyID": "0"}]}
    monkeypatch.setattr(gamedata, "table_rows", lambda table, *a, **k: tables.get(table, []))
    if hasattr(gamedata.spell_cooldowns, "cache_clear"):
        gamedata.spell_cooldowns.cache_clear()
    cds = gamedata.spell_cooldowns()
    assert cds[871] == (180.0, 1) and cds[12975] == (180.0, 1)
    if hasattr(gamedata.spell_cooldowns, "cache_clear"):
        gamedata.spell_cooldowns.cache_clear()


def test_a_filtered_table_keeps_its_own_rows_only(tmp_path, monkeypatch):
    """wago.tools' filter matches a prefix: SpellEffect of SpellID 100 (Charge) came with 100002, 10001... and the
    tank sheet listed Charge among the short defensives."""
    from paf import gamedata

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    gamedata._filtered_rows.cache_clear()  # read once a process: this test's file, not a real one read before
    f = tmp_path / "gamedata" / "filtered" / "SpellEffect-SpellID-100.csv"
    f.parent.mkdir(parents=True)
    f.write_text("ID,SpellID,EffectAura,ImplicitTarget_0\n1,100,0,6\n2,10001,87,1\n3,100002,79,18\n", encoding="utf-8")
    assert [r["ID"] for r in gamedata._filtered_rows("SpellEffect", "SpellID", 100)] == ["1"]
    assert not gamedata.is_mitigation(100) and not gamedata.weakens_enemy(100)
    gamedata._filtered_rows.cache_clear()


def test_a_movement_button_is_a_speed_buff_and_nothing_else(monkeypatch):
    # Divine Steed: a scripted cast (a dummy) whose buff of the same name raises run speed; Celestial Conduit also
    # raises it, but heals as a channel: throughput
    effects = {190784: [{"Effect": "3", "EffectAura": "0"}],
               221883: [{"Effect": "6", "EffectAura": "31"}, {"Effect": "6", "EffectAura": "87"}],
               443028: [{"Effect": "6", "EffectAura": "31"}, {"Effect": "6", "EffectAura": "23"}],
               443039: [{"Effect": "10", "EffectAura": "0"}]}
    names = {190784: "Divine Steed", 221883: "Divine Steed", 443028: "Celestial Conduit", 443039: "Celestial Conduit"}
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda table, col, value: effects.get(value, []))
    monkeypatch.setattr(gamedata, "spell_names", lambda locale="": names)
    gamedata.same_name_spells.cache_clear()
    try:
        assert gamedata.is_speed(190784) and not gamedata.is_speed(443028)
    finally:
        gamedata.same_name_spells.cache_clear()


def test_a_utility_button_is_a_pure_dispel_a_knockback_or_a_move(monkeypatch):
    # Mass Dispel (dispel, trigger, dummy) and Ring of Peace (knockback) are utility; Revival dispels and heals
    effects = {32375: [{"Effect": "38"}, {"Effect": "64"}, {"Effect": "3"}],
               116844: [{"Effect": "179"}], 142895: [{"Effect": "144"}],
               115310: [{"Effect": "38"}, {"Effect": "10"}]}
    names = {32375: "Mass Dispel", 116844: "Ring of Peace", 142895: "Ring of Peace", 115310: "Revival"}
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda table, col, value: effects.get(value, []))
    monkeypatch.setattr(gamedata, "spell_names", lambda locale="": names)
    gamedata.same_name_spells.cache_clear()
    try:
        assert gamedata.is_utility(32375) and gamedata.is_utility(116844) and not gamedata.is_utility(115310)
    finally:
        gamedata.same_name_spells.cache_clear()


def test_a_ramp_button_changes_spells_and_heals_nothing(monkeypatch):
    # Evangelism (dummy, spell mods) is a ramp's button; Celestial Conduit changes spells too but heals as a channel
    effects = {472433: [{"Effect": "3", "EffectAura": "0"}, {"Effect": "6", "EffectAura": "108"}],
               443028: [{"Effect": "6", "EffectAura": "23"}, {"Effect": "6", "EffectAura": "108"}],
               443039: [{"Effect": "10", "EffectAura": "0"}]}
    names = {472433: "Evangelism", 443028: "Celestial Conduit", 443039: "Celestial Conduit"}
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda table, col, value: effects.get(value, []))
    monkeypatch.setattr(gamedata, "spell_names", lambda locale="": names)
    gamedata.same_name_spells.cache_clear()
    try:
        assert gamedata.is_ramp_kind(472433) and not gamedata.is_ramp_kind(443028)
    finally:
        gamedata.same_name_spells.cache_clear()


def test_a_magic_only_cut_and_a_physical_hit(monkeypatch):
    # Spell Reflection (23920) triggers 385391: -20% magic damage taken (mask 126); Shield Wall -40% of every school
    rows = {23920: [{"Effect": "6", "EffectAura": "28", "EffectBasePointsF": "100"},
                    {"Effect": "64", "EffectTriggerSpell": "385391"}],
            385391: [{"Effect": "6", "EffectAura": "87", "EffectBasePointsF": "-20", "EffectMiscValue_0": "126"}],
            871: [{"Effect": "6", "EffectAura": "87", "EffectBasePointsF": "-40", "EffectMiscValue_0": "127"}]}
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda _t, _c, sid, locale="": rows.get(sid, []))
    assert gamedata.magic_only(23920) and not gamedata.magic_only(871)
    assert gamedata.physical_only("Melee")


def test_a_raid_button_by_the_game_data(monkeypatch):
    # Spirit Link Totem summons a totem; Innervate gives mana and haste: no raid button (round 58)
    rows = {98008: [{"Effect": "28"}, {"Effect": "3"}], 29166: [{"Effect": "6", "EffectAura": "21"}],
            220207: [{"Effect": "6", "EffectAura": "23", "EffectTriggerSpell": "220214"}],
            220214: [{"Effect": "136"}]}
    monkeypatch.setattr(gamedata, "_filtered_rows", lambda _t, _c, sid, locale="": rows.get(sid, []))
    assert gamedata.raid_kind(98008) and gamedata.raid_kind(220207) and not gamedata.raid_kind(29166)
