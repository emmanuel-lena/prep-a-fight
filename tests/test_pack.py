import io
from datetime import UTC, datetime

from paf import pack
from paf.actions import Action
from paf.assigns import Mechanic
from paf.corpus.timeline import Ability, Timeline
from paf.fight import AddWave, Fight
from paf.raidneed import AddType
from paf.talent_sim import Build


def test_refresh_is_daily_at_4am_paris():
    summer = datetime(2026, 7, 10, 1, 59, tzinfo=UTC)  # 03:59 in Paris (UTC+2)
    assert pack.last_refresh(summer).isoformat() == "2026-07-09T04:00:00+02:00"
    assert pack.last_refresh(datetime(2026, 7, 10, 2, 0, tzinfo=UTC)).isoformat() == "2026-07-10T04:00:00+02:00"
    winter = datetime(2026, 12, 10, 3, 0, tzinfo=UTC)  # 04:00 in Paris (UTC+1)
    assert pack.last_refresh(winter).isoformat() == "2026-12-10T04:00:00+01:00"
    assert pack.is_stale("2026-12-10T02:59:00+00:00", winter)
    assert not pack.is_stale("2026-12-10T03:00:00+00:00", winter)
    assert pack.is_stale("not a date")


def _pack() -> pack.PackData:
    fight = Fight("Boss", 300, [AddWave(30, 3, 20, "Imp")], movement_scale=0.5)
    tl = Timeline("Boss", "mythic", "Elemental", 199, 300, [("P1", 0.0, False)], [(30, 3, 20, "Imp")],
                  [Ability(114050, "Ascendance", 0.9, 2)],
                  [{"rank": 1, "dps": 300e3, "ilvl": 330, "duration": 300, "casts": {114050: [10.0, 190.0]},
                    "targets": [(0.0, 30.0, "Boss")], "report": "SECRET", "name": "Somebody"}],
                  [("Big Hit", [50.0])], "Boss", {"Big Hit": 1234})
    return pack.PackData(3470, 5, "Shaman", "Elemental", "2026-10-06T10:00:00+00:00", 199, "Boss", fight,
                         [("P1", 0.0)], 0.38, 0.12, 0.88, (0.98, 1.01, 1.03), tl, tl,
                         [Build(frozenset({1, 2}), [{"rank_pos": 3}], "CODE", "top build A")],  # corpus rows
                         [AddType("Imp", 199, 20, 0.3, {"Elemental Shaman": 0.4}, 0.2, 5e5, 4e5, {"Fire Mage"})],
                         [Mechanic("interrupt:1", "Kick me", "interrupt", [60.0], 0.0, 10, 1.0, 2.0, 0.5)],
                         [Action("interrupt", "Kick me", "kick it")])


def test_pack_roundtrip_without_names_or_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    p = _pack()
    text = pack.to_json(p)
    assert "SECRET" not in text and "Somebody" not in text
    path = pack.save(p)
    assert path.name == "3470-5.json" and path.parent.name == "shaman-elemental"
    q = pack.load(3470, 5, "Shaman", "Elemental")
    assert q.fight.movement_scale == 0.5 and q.fight.add_waves[0].name == "Imp"
    assert q.timeline.players[0]["casts"][114050] == [10.0, 190.0] and q.timeline.abilities[0].name == "Ascendance"
    b = q.builds[0]
    assert b.count == 1 and b.median_rank == 3 and b.key == frozenset({1, 2}) and b.code == "CODE"
    assert q.add_types[0].estimated == {"Fire Mage"} and q.add_types[0].rate([("Elemental Shaman", 100.0)]) == 40.0
    assert q.mechanics[0].per_kill == 2.0 and q.actions[0].text == "kick it" and q.validation == (0.98, 1.01, 1.03)
    assert pack.load(1, 5, "Shaman", "Elemental") is None


class _Resp:
    def __init__(self, body=b""):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_shared_packs_through_the_relay(tmp_path, monkeypatch):
    import urllib.error

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setenv("PAF_FEEDBACK_URL", "https://relay.example.workers.dev")
    store = {}

    def fake(url, data=None, method="GET"):
        k = url.split("/packs/", 1)[1]
        if method == "PUT":
            if k in store:
                raise urllib.error.HTTPError(url, 409, "conflict", {}, io.BytesIO(b"not newer than the current pack"))
            store[k] = data
            return _Resp(b"{}")
        if k not in store:
            raise urllib.error.HTTPError(url, 404, "no pack", {}, io.BytesIO(b"no pack"))
        return _Resp(store[k])

    monkeypatch.setattr(pack, "_request", fake)
    assert pack.fetch_shared(3470, 5, "Shaman", "Elemental") is None
    assert pack.publish(_pack()) == "shared with the other players"
    assert "not newer" in pack.publish(_pack())
    assert list(store) == ["shaman-elemental/3470-5"]
    got = pack.fetch_shared(3470, 5, "Shaman", "Elemental")
    assert got.kills == 199 and pack.load(3470, 5, "Shaman", "Elemental") is not None  # kept locally too
    monkeypatch.setenv("PAF_FEEDBACK_URL", "https://discord.com/api/webhooks/1/x")
    assert pack.relay() == "" and "no relay" in pack.publish(_pack())
