from types import SimpleNamespace

from paf import demands, encmodel
from paf.corpus import db
from paf.mechanics import Section

# The Coiled Altar mythic, as the game data has it (2026-11-12): Eternal Nightfall a 17 s cast; under it Veil of
# Twilight, an absorb on its caster (4902 mythic, 1472 heroic); Spiritcackle brings Spiteful Soulcoilers at -99%;
# Ghastly Regeneration +100% for 35 s
EFFECTS = {
    1286918: [{"DifficultyID": "16", "EffectIndex": "0", "Effect": "2", "EffectBasePointsF": "300",
               "ImplicitTarget_0": "22"}],
    1286912: [{"DifficultyID": "0", "EffectIndex": "0", "Effect": "6", "EffectAura": "69", "EffectBasePointsF": "1000",
               "ImplicitTarget_0": "1"},
              {"DifficultyID": "16", "EffectIndex": "0", "Effect": "6", "EffectAura": "69",
               "EffectBasePointsF": "4902", "ImplicitTarget_0": "1"},
              {"DifficultyID": "15", "EffectIndex": "0", "Effect": "6", "EffectAura": "69",
               "EffectBasePointsF": "1472", "ImplicitTarget_0": "1"}],
    1309105: [{"DifficultyID": "0", "EffectIndex": "0", "Effect": "6", "EffectAura": "87", "EffectBasePointsF": "-99",
               "ImplicitTarget_0": "1"}],
    1304033: [{"DifficultyID": "0", "EffectIndex": "1", "Effect": "6", "EffectAura": "87", "EffectBasePointsF": "100",
               "ImplicitTarget_0": "1"}],
}
MISC = {1286918: {"CastingTimeIndex": "299", "DurationIndex": "8"}, 1304033: {"CastingTimeIndex": "1",
                                                                          "DurationIndex": "125"}}


def _sec(i, title, kind, spell=0, flags=(), children=()):
    return Section(i, title, kind, spell, list(flags), "", 0, i, -1, list(children))


def journal():
    return [
        _sec(1, "Overview", "overview"),
        _sec(2, "Stage Two: Usurper's Reprisal", "stage", children=[
            _sec(3, "Eternal Nightfall", "ability", 1286918, ["deadly"],
                 [_sec(4, "Veil of Twilight", "ability", 1286912)]),
            _sec(5, "Spiritcackle", "ability", 1286441, children=[
                _sec(6, "Spiteful Soulcoiler", "creature", children=[_sec(7, "Spirit Shield", "ability", 1309105)])]),
            _sec(8, "Gravebound", "ability", 1286837, children=[_sec(9, "Soul Fragment", "creature")])]),
        _sec(10, "Intermission: The Claimed Vessel", "stage", children=[
            _sec(11, "Soulbinding", "ability", 1304032,
                 children=[_sec(12, "Ghastly Regeneration", "ability", 1304033)])]),
        _sec(13, "Stage Three: Coiled Union", "stage", children=[
            _sec(14, "Hex Lord Malacrass", "creature", children=[
                _sec(15, "Eternal Nightfall", "ability", 1286918, children=[
                    _sec(16, "Veil of Twilight", "ability", 1286912)])])]),
    ]


def model(monkeypatch, difficulty="mythic"):
    monkeypatch.setattr("paf.mechanics.encounter_sections", lambda enc: journal())
    monkeypatch.setattr("paf.gamedata._filtered_rows",
                        lambda table, col, spell: EFFECTS.get(spell, []) if table == "SpellEffect"
                        else [MISC[spell]] if spell in MISC else [])
    monkeypatch.setattr(encmodel, "_times", lambda: ({"299": 17.0, "1": 0.0}, {"8": 15.0, "125": 35.0}))
    monkeypatch.setattr(encmodel, "_severities", lambda: {1286918: 2, 1286441: 1})
    monkeypatch.setattr(encmodel, "journal_creatures",
                        lambda enc: frozenset({"Hex Lord Malacrass", "Spiteful Soulcoiler"}))
    return encmodel.build(3429, difficulty)


def test_the_model_reads_what_each_spell_does_from_the_game_data(monkeypatch):
    m = model(monkeypatch)
    assert m.stages == ["Stage Two: Usurper's Reprisal", "Intermission: The Claimed Vessel",
                        "Stage Three: Coiled Union"]
    night = m.ability(1286918)
    assert (night.cast, night.duration, night.severity, "deadly" in night.flags) == (17.0, 15.0, 2, True)
    veil = m.ability(1286912)
    assert veil.parent == 1286918 and veil.has("shield", on_caster=True)[0].size == 4902  # mythic over the default
    assert model(monkeypatch, "heroic").ability(1286912).effects[0].size == 1472
    assert [(c.name, c.summoner) for c in m.creatures][:2] == [("Spiteful Soulcoiler", 1286441), ("Soul Fragment",
                                                                                                    1286837)]


def test_the_demands_the_game_data_shows_before_any_log(monkeypatch):
    by = {w.label: w for w in demands.from_model(model(monkeypatch))}
    veil = by["Veil of Twilight"]
    assert veil.kind == "shield" and veil.severity == 2 and veil.unit == "Hex Lord Malacrass"  # the unit: Stage Three's
    assert veil.detail == "to break within Eternal Nightfall's 17 s cast, 4902 units (mythic)"
    assert by["Spirit Shield"].kind == "immune" and by["Spirit Shield"].unit == "Spiteful Soulcoiler"
    amp = by["Ghastly Regeneration"]
    assert amp.kind == "amp" and amp.detail == "+100% damage taken for 35 s"
    assert by["Spiteful Soulcoiler"].kind == "adds" and "Soul Fragment" not in by  # an object of the fight, no unit


def test_a_shield_s_up_and_broken_times_and_its_absorb():
    # a top raid (2026-11-12): Veil of Twilight up 230.5 s, broken 242.9 s, 34.8 M
    evs = [{"timestamp": 1000 + 230500, "type": "applybuff", "abilityGameID": 1286912, "targetID": 619,
            "absorb": 34828260},
           {"timestamp": 1000 + 242900, "type": "removebuff", "abilityGameID": 1286912, "targetID": 619, "absorb": 0},
           {"timestamp": 1000 + 500000, "type": "applybuff", "abilityGameID": 1286912, "targetID": 619}]  # still up
    assert demands.shield_events(evs, 1000) == [(1286912, 230.5, 242.9, 34828260.0)]


def test_the_logs_place_the_shields_and_the_fight_its_adds_and_amps(tmp_path, monkeypatch):
    m = model(monkeypatch)
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    con = db.connect()
    con.executescript(demands.SCHEMA)
    for i, (t0, took) in enumerate([(230, 12), (240, 16), (235, 14)]):
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, kill, status) "
                    "VALUES(?, 1, 3429, 5, 1, 'done')", (f"r{i}",))
        con.execute("INSERT INTO enemy_shield VALUES(?, 1, 1286912, ?, ?, 35e6)", (f"r{i}", t0, t0 + took))
        con.execute("INSERT INTO enemy_shield VALUES(?, 1, 1286912, ?, ?, 35e6)",
                    (f"r{i}", t0 + 2, t0 + took))  # the same wave
        con.execute("INSERT INTO shield_status VALUES(?, 1)", (f"r{i}",))
    con.execute("INSERT INTO enemy_shield VALUES('r0', 1, 1286912, 400, 410, 35e6)")  # a 2nd in one kill of 3: left
    fight = SimpleNamespace(
        add_waves=[SimpleNamespace(name="Spiteful Soulcoiler", time=195, lifetime=25),
                   SimpleNamespace(name="Hex Lord Malacrass", time=171, lifetime=212)],  # a second boss: no burst
        vulnerable=[SimpleNamespace(name="Ghastly Regeneration (boss aura)", start=391, duration=35, multiplier=2)],
        lust_time=392)
    by = {w.label: w for w in demands.place(demands.from_model(m), m, con, 3429, 5, None, fight)}
    assert by["Veil of Twilight"].spans == [(235.0, 249.0)]
    assert by["Veil of Twilight"].detail.endswith("; the top raids break it in 14 s, 35.0 M")
    assert by["Spiteful Soulcoiler"].spans == [(195, 220)]
    assert by["Ghastly Regeneration"].spans == [(391, 426)]  # the measured aura, in the sims' time
    assert by["Ghastly Regeneration"].detail.endswith("Bloodlust in it")
    assert by["Spirit Shield"].spans == [(195, 220)]  # while its unit lives
    assert by["Spirit Shield"].detail == "-99% damage taken, while Spiteful Soulcoiler lives"
    assert "Hex Lord Malacrass" not in by


def test_each_spec_s_damage_in_each_placed_window():
    w = demands.Window("adds", "Spawn of Vexhul", [(1, 3)])
    unplaced = demands.Window("immune", "Spirit Shield")
    got = demands.compare([w, unplaced], {"Subtlety": [1, 10, 10, 1], "Outlaw": [5, 5, 5, 5]})
    assert got == {"Subtlety": {"all": 22, "Spawn of Vexhul": 20}, "Outlaw": {"all": 20, "Spawn of Vexhul": 10}}


def test_the_sheet_says_the_spec_ahead_in_each_window():
    # Twin Fangs mythic, the owner's Rogue: Outlaw +16% on the whole fight, Subtlety the burst on the adds
    from paf import briefing

    d = SimpleNamespace(specs={"mine": "Subtlety"}, demands={
        "windows": [{"kind": "adds", "label": "Spawn of Vexhul", "spans": [(35, 46)], "detail": "5 waves", "unit": "",
                     "severity": 1},
                    {"kind": "immune", "label": "Spirit Shield", "spans": [], "detail": "", "unit": "Soulcoiler",
                     "severity": None}],
        "damage": {"Subtlety": {"all": 120.7, "Spawn of Vexhul": 38.4},
                   "Outlaw": {"all": 140.0, "Spawn of Vexhul": 35.6}}})
    html = briefing.demands_html(d)
    assert "What this fight demands" in html and "Spawn of Vexhul</span>" in html
    assert "class='dm-w immune off'" in html and "not seen in the top kills" in html  # unplaced: said, not drawn
    assert "<td class='pos dm-best'>+16%</td>" in html and "<td class='neg'>-7%</td>" in html
    assert "<td class='dm-me dm-best'>your spec, best</td>" in html and "<th>Spirit Shield</th>" not in html
    d.demands["damage"] = {}
    assert "dm-grid" not in briefing.demands_html(d)  # no other spec ticked: the windows only


def test_the_boss_out_of_reach_is_placed_on_its_immune_phases_and_windows_end_with_the_fight(monkeypatch, tmp_path):
    # the audit (2026-11-12): Deathguard on Malacrass and Vitriolic Homeostasis had no unit; a wave ran past the kill
    m = model(monkeypatch)
    m.boss = "Hex Lord Malacrass"
    m.abilities.append(encmodel.Ability(1304028, "Deathguard", "Intermission: The Claimed Vessel", "", [], None, 0.0,
                                        None, [encmodel.Effect("damage_taken", -99, True)]))
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    con = db.connect()
    fight = SimpleNamespace(add_waves=[SimpleNamespace(name="Spiteful Soulcoiler", time=600, lifetime=40)],
                            vulnerable=[], invulnerable=[SimpleNamespace(start=169, duration=219)], lust_time=0,
                            duration=625)
    by = {w.label: w for w in demands.place(demands.from_model(m), m, con, 3429, 5, None, fight)}
    assert by["Deathguard"].unit == "Hex Lord Malacrass" and by["Deathguard"].spans == [(169, 388)]
    assert by["Spiteful Soulcoiler"].spans == [(600, 625)]  # cut at the kill
