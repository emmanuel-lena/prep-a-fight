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
