from types import SimpleNamespace

from paf import apl, rotation, workshop_views


def log():
    """A 120 s pull: a DoT (18 s) refreshed twice by its own cast, once too early; a builder at the cap; a 60 s
    cooldown cast once."""
    names = {1: "Flame Shock", 2: "Lava Burst", 3: "Ascendance", 4: "Earth Shock"}
    casts = [rotation.Cast(0.0, 1, (11, 0, 100), 5), rotation.Cast(1.0, 3, (11, 0, 100), 5)]
    for i in range(10):  # builder +10, then the spender
        t = 2.0 + i
        casts.append(rotation.Cast(t, 2, (11, 100 if i in (3, 4) else i * 10, 100), 5))
    casts += [rotation.Cast(13.0, 4, (11, 90, 100), 5), rotation.Cast(14.0, 2, (11, 0, 100), 5)]
    casts += [rotation.Cast(t, 1, (11, 0, 100), 5) for t in (4.0, 24.0, 42.0, 60.0)]
    debuffs = [(0.0, "applydebuff", 1, 5), (4.0, "refreshdebuff", 1, 5), (24.0, "refreshdebuff", 1, 5),
               (42.0, "refreshdebuff", 1, 5), (60.0, "refreshdebuff", 1, 5), (80.0, "removedebuff", 1, 5)]
    return rotation.Log(120.0, sorted(casts, key=lambda c: c.t), debuffs, names)


def test_dots_early_refreshes_by_their_own_cast():
    d = rotation.dots(log(), {1: 18.0})[0]
    assert d.name == "Flame Shock" and d.duration == 18.0 and d.refreshes == 4
    assert d.early == 1  # at 4 s with 14 s left; then 3.4 s left each time (inside the 5.4 s window)


def test_builders_at_the_cap_and_cooldowns_from_the_apl():
    w = rotation.waste(log())
    assert [(x.builder, x.capped) for x in w] == [("Lava Burst", 2)]
    cds = rotation.cooldowns(log(), {3: (60.0, 1), 1: (6.0, 1)}, {"ascendance"})
    assert [(c.name, c.casts, c.possible) for c in cds] == [("Ascendance", 1, 2)]  # 1 + 119 // 60


def test_contexts_compare_shares_with_the_sim():
    lg = log()
    windows = [1] * 24  # 120 s of single target
    sims = {"st": {"lavaburst": ("Lava Burst", 20.0), "flameshock": ("Flame Shock", 2.0),
                   "earthshock": ("Earth Shock", 5.0)}}
    ctx = rotation.contexts(lg, windows, sims, {"lavaburst", "flameshock", "earthshock"})
    assert [c.key for c in ctx] == ["st"]
    rows = {r.name: r for r in ctx[0].rows}
    assert round(rows["Lava Burst"].sim, 2) == round(20 / 27, 2)
    assert rows["Flame Shock"].player > rows["Flame Shock"].sim
    r = rotation.Review("Me", "Elemental Shaman", "pull 1", 120.0, rotation.dots(lg, {1: 18.0}), rotation.waste(lg),
                        rotation.cooldowns(lg, {3: (60.0, 1)}, {"ascendance"}), ctx)
    d = rotation.to_dict(r)
    assert d["highlights"] and any("Flame Shock" in h for h in d["highlights"])
    page = workshop_views.render({"kind": "rotation", "boss": "Boss", **d})
    assert "To work on" in page and "Your spells, by number of targets" in page and "Your cooldowns" in page


def test_the_apl_names_and_tokens():
    assert apl.simc_tokens("DeathKnight", "BeastMastery") == ("deathknight", "beast_mastery")
    lines = ["actions=ascendance,if=x", "actions+=/use_item,name=y", "actions.aoe+=/call_action_list,name=z",
             "actions.st+=/lava_burst/flame_shock,target_if=min:dot.flame_shock.remains"]
    assert apl.spells(lines) == {"ascendance", "lavaburst", "flameshock"}


def test_the_raid_board(tmp_path, monkeypatch):
    from paf import web

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "prep-nek-zali-mythic-elemental-shaman.html").write_text("<title>Nek'zali prep</title>")
    encs = [SimpleNamespace(id=1, name="Nek'zali"), SimpleNamespace(id=2, name="Vashnik")]
    html = web.raid_board(encs, "Shaman", "Elemental")
    assert html.count("rb-d ok") == 1 and html.count("rb-d no") == 5  # 2 bosses x 3 difficulties
    assert html.count("rb-boss grey") == 1  # Vashnik: nothing prepared
    assert "/view/nek-zali-mythic-elemental-shaman" in html and "/boss?boss=2&amp;difficulty=heroic" in html
    assert "rb-frame tri" in html and "rb-frame sq" in html and "rb-frame penta" in html



def test_buffs_next_to_the_top_players():
    import sqlite3

    from paf.corpus.db import SCHEMA

    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.execute("INSERT INTO ability VALUES(7, 'Master of the Elements')")
    for k in range(4):  # 100 s kills, the buff up 60 s
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 5, 100, 'done')", (f"r{k}",))
        con.execute("INSERT INTO player_buff VALUES(?, 1, 1, 7, 'applybuff', 10, 1)", (f"r{k}",))
        con.execute("INSERT INTO player_buff VALUES(?, 1, 1, 7, 'removebuff', 70, 1)", (f"r{k}",))
    tops = rotation.tops_buffs(con, 9, 5)
    assert tops == {7: ("Master of the Elements", 0.6)}
    rows = rotation.buff_rows({7: ("x", 0.3)}, tops)
    assert [(b.name, b.player, b.tops) for b in rows] == [("Master of the Elements", 0.3, 0.6)]
    r = rotation.Review("Me", "Elemental Shaman", "pull 1", 100.0, buffs=rows)
    assert any(t == "Master of the Elements: you had it 30% of the pull; the top players of your spec keep it up 60% "
               "of the fight." for _, t in rotation.highlights(r))
