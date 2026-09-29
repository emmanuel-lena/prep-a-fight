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
