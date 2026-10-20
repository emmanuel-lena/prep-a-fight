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
    f = tmp_path / "gamedata" / "filtered" / "SpellEffect-SpellID-100.csv"
    f.parent.mkdir(parents=True)
    f.write_text("ID,SpellID,EffectAura,ImplicitTarget_0\n1,100,0,6\n2,10001,87,1\n3,100002,79,18\n", encoding="utf-8")
    assert [r["ID"] for r in gamedata._filtered_rows("SpellEffect", "SpellID", 100)] == ["1"]
    assert not gamedata.is_mitigation(100) and not gamedata.weakens_enemy(100)
