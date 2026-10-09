import json
import sqlite3
from types import SimpleNamespace

from paf import healer
from paf.corpus.db import SCHEMA


def test_raid_damage_curve_and_its_big_moments():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    for k in range(3):  # 60 s kills, 2 players, a burst at 30 s
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 4, 60, 'done')", (f"r{k}",))
        base = [100.0] * 12
        base[6] = 500.0  # 30-35 s
        healer.ensure_table(con)
        con.execute("INSERT INTO raid_damage VALUES(?, 1, 5.0, ?)", (f"r{k}", json.dumps({"A": base, "B": base})))
    curve = healer.raid_curve(con, 9, 4, 60.0)
    assert curve[0] == 200.0 and curve[6] == 1000.0
    found = healer.moments(curve, [("Venom Burst", [27.0]), ("Far Away", [5.0])])
    assert [(m.t, m.boss_spell) for m in found] == [(30.0, "Venom Burst")] and round(found[0].ratio) == 5


def test_cooldowns_where_the_top_healers_press_them():
    ab = SimpleNamespace(id=1, name="Spirit Link Totem", users=0.9, per_kill=2.0)
    rare = SimpleNamespace(id=2, name="Healing Wave", users=1.0, per_kill=80.0)  # spammed: not a cooldown
    players = [{"casts": {1: [29.0, 150.0]}} for _ in range(5)]
    tl = SimpleNamespace(abilities=[ab, rare], duration=240.0, players=players)
    found = [healer.Moment(30.0, 1000.0, 5.0, "Venom Burst")]
    cds = healer.cooldowns(tl, found, {1: (180.0, 1), 2: (0.0, 1)})
    assert [c.name for c in cds] == ["Spirit Link Totem"]
    assert cds[0].times == [29.0, 150.0] and cds[0].near == ["0:30 Venom Burst", ""]
    h = healer.HealerPrep("Boss", "heroic", "Restoration Shaman", 5, 240.0, [100.0] * 48, found, cds,
                          [(3, "top build A", "ABC")], [("Trinket", 1, 0.5)], ["Dispel the poison."], [])
    page = healer.render(h)
    assert "Your healing cooldowns" in page and "Spirit Link Totem" in page and "QE Live" in page
    assert "data-copy='ABC'" in page and "Dispel the poison." in page
