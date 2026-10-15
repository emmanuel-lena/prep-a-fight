import json
import subprocess
import sys
import time

import pytest

from paf import web
from paf.jobrun import SESSION


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    (tmp_path / "web").mkdir()
    return tmp_path


def job_file(home, jid: str, pid: int, status: str = "running") -> None:
    meta = {"args": ["prep", "3455", "--difficulty", "mythic"], "result": "", "status": status,
            "started": time.time(), "pid": pid}
    (home / "web" / f"job-{jid}.json").write_text(json.dumps(meta), encoding="utf-8")
    (home / "web" / f"job-{jid}.log").write_text("== Collecting\n", encoding="utf-8")


def test_a_prep_pauses_with_its_children_and_resumes_with_the_same_command(home, monkeypatch):
    # a prep and the simc it started: pausing stops both
    child = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
             " time.sleep(60)")
    proc = subprocess.Popen([sys.executable, "-c", child], **SESSION)
    time.sleep(0.5)
    jobs = web.Jobs()
    job_file(home, "abcd1234", proc.pid)
    assert jobs.pause("abcd1234", "update")
    proc.wait(timeout=10)
    assert jobs.get("abcd1234")["status"] == "paused" and jobs.paused("update") == ["abcd1234"]
    started = []
    monkeypatch.setattr(jobs, "start", lambda args, result: started.append(args) or "ffff0000")
    assert jobs.resume("abcd1234") == "ffff0000"
    assert started == [["prep", "3455", "--difficulty", "mythic"]]
    assert jobs.get("abcd1234")["status"] == "resumed" and jobs.paused() == []
    assert jobs.resume("abcd1234") == "ffff0000"  # a second click follows the resumed prep


def test_a_finished_prep_cannot_be_paused(home):
    job_file(home, "00000001", 0, status="done")
    assert not web.Jobs().pause("00000001")


def test_the_update_pauses_what_runs_instead_of_refusing(home, monkeypatch):
    from paf import update

    monkeypatch.setattr(update, "STATE", {"release": type("R", (), {"version": "9.9.9", "url": "u"})()})
    monkeypatch.setattr(update, "install_dir", lambda: home)
    monkeypatch.setattr(web, "busy", lambda: "A prep is running")
    page = web.run_update()
    assert "Pause it and update" in page and "name='pause'" in page
