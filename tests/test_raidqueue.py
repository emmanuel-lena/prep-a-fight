from dataclasses import dataclass

import pytest

from paf import raidqueue


@dataclass
class Enc:
    id: int
    name: str


ENCS = [Enc(1, "Ula'tek"), Enc(2, "Nek'zali"), Enc(3, "The Lost Explorers")]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    return tmp_path


def test_a_queue_skips_the_bosses_prepared_this_week(home):
    q = raidqueue.build(ENCS, "heroic", "zapper-shaman", {2})
    assert [i["status"] for i in q["items"]] == ["waiting", "ready", "waiting"]
    raidqueue.save(q)
    assert raidqueue.load()["items"][1]["name"] == "Nek'zali"
    assert raidqueue.progress(q) == (1, 3, None)


def test_the_full_analyses_come_after_every_first_sheet(home, monkeypatch):
    monkeypatch.setattr(raidqueue, "_pending", lambda boss, diff: 120 if boss == 3 else 0)
    q = raidqueue.build(ENCS, "heroic", "x", set())
    assert raidqueue._next(q)["boss"] == 1
    for i in q["items"]:
        i["status"] = "done"
    nxt = raidqueue._next(q)  # every sheet made: the bosses with kills left get their full pass
    assert (nxt["boss"], nxt["pass"]) == (3, "full")
    assert raidqueue.progress(q)[:2] == (3, 3)


def test_the_board_shows_queued_bosses_only_while_the_runner_lives(home, monkeypatch):
    q = raidqueue.build(ENCS, "mythic", "x", set())
    q["pid"] = 4242
    monkeypatch.setattr("paf.web.pid_alive", lambda pid: True)
    assert raidqueue.waiting(q, "mythic") == {1, 2, 3} and raidqueue.waiting(q, "heroic") == set()
    assert raidqueue.active(q)
    monkeypatch.setattr("paf.web.pid_alive", lambda pid: False)
    assert raidqueue.waiting(q, "mythic") == set() and not raidqueue.active(q)


def test_a_stop_asked_meanwhile_is_kept(home):
    q = raidqueue.build(ENCS, "heroic", "x", set())
    raidqueue.save(q)
    raidqueue.stop()  # from the app or the icon's menu, while the runner holds its own copy
    raidqueue._keep(q)
    assert raidqueue.load()["stop"] is True


def test_the_estimate_shares_one_quota(home, monkeypatch):
    from paf import estimate

    def plan(con, enc, diff, cls, spec, client=None):
        return estimate.Estimate("collect", 4 + 8, kills=100, sims=8)

    monkeypatch.setattr(estimate, "plan", plan)

    class Client:
        def rate_limit(self):
            return {"limitPerHour": 3600, "pointsSpentThisHour": 3000, "pointsResetIn": 1200}

    est = raidqueue.estimate(None, ENCS, 4, "Shaman", "Elemental", Client())
    # 3 x 100 kills x 12 points = 3600 > the 600 left: the reset in 20 min
    assert est.collect == 3 and est.wait == pytest.approx(20)
    assert est.minutes == pytest.approx(3 * 12 + 20)


def test_start_refuses_while_a_queue_runs(home, monkeypatch):
    q = raidqueue.build(ENCS, "heroic", "x", set())
    q["pid"] = 4242
    raidqueue.save(q)
    monkeypatch.setattr("paf.web.pid_alive", lambda pid: True)
    started = []
    monkeypatch.setattr(raidqueue, "spawn_runner", lambda: started.append(1))
    assert raidqueue.start(raidqueue.build(ENCS, "mythic", "x", set())) is False and not started
    monkeypatch.setattr("paf.web.pid_alive", lambda pid: False)
    assert raidqueue.start(raidqueue.build(ENCS, "mythic", "x", set())) is True and started


def test_no_update_while_the_raid_is_being_prepared(tmp_path, monkeypatch):
    from paf import lastraid, raidlead, raidqueue, web

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setattr(lastraid, "runner_alive", lambda *a: False)
    monkeypatch.setattr(raidlead, "runner_alive", lambda *a: False)
    monkeypatch.setattr(raidqueue, "active", lambda q: False)
    assert web.busy() == ""
    monkeypatch.setattr(raidqueue, "active", lambda q: True)
    assert web.busy() == "Your raid is being prepared"


def test_a_queue_cut_off_by_a_shutdown_goes_on_at_launch(home, monkeypatch):
    from paf import characters

    monkeypatch.setattr(characters, "current_slug", lambda: "zapper-shaman")
    started = []
    monkeypatch.setattr(raidqueue, "spawn_runner", lambda: started.append(1))
    q = raidqueue.build(ENCS, "heroic", "zapper-shaman", set())
    q["items"][0]["status"], q["items"][1]["status"], q["pid"] = "done", "running", 999999  # its runner is gone
    raidqueue.save(q)
    assert raidqueue.resume() and started
    q["stop"] = True  # stopped by the player: stays stopped
    raidqueue.save(q)
    assert not raidqueue.resume() and len(started) == 1


def test_a_queue_paused_by_an_update_goes_on_at_launch(home, monkeypatch):
    from paf import characters

    monkeypatch.setattr(characters, "current_slug", lambda: "zapper-shaman")
    started = []
    monkeypatch.setattr(raidqueue, "spawn_runner", lambda: started.append(1))
    q = raidqueue.build(ENCS, "heroic", "zapper-shaman", set())
    q["pid"] = 999999
    raidqueue.save(q)
    raidqueue.pause("update")
    assert raidqueue.load()["paused"] == "update" and raidqueue.load()["stop"]
    assert raidqueue.resume() and started  # the app opens again after the update: the queue goes on
    assert not raidqueue.load()["stop"] and raidqueue.load()["paused"] == ""
