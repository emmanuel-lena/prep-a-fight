"""A command of the app run as one of its jobs from a background process (paf.raidqueue, paf.lastraid): the same job
files as the jobs the app starts itself (<data>/web/job-<id>.json and .log), so its pages, banners and the raid
board show it, and it outlives the window.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from paf.config import data_dir


def run_job(args: list[str], result: Path | None = None, should_stop: Callable[[], bool] | None = None,
            on_start: Callable[[str], None] | None = None, log=print) -> tuple[str, str]:
    """Run `paf <args>` to its end: (job id, 'done' | 'failed' | 'stopped'). should_stop is asked every 2 s (the job
    is then stopped); on_start gets the job id as soon as it runs."""
    from paf.web import _env, _python

    jid = uuid.uuid4().hex[:8]
    folder = data_dir() / "web"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"args": args, "result": str(result or ""), "status": "running", "started": time.time(), "pid": None}

    def save() -> None:
        (folder / f"job-{jid}.json").write_text(json.dumps(meta), encoding="utf-8")

    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW
    with (folder / f"job-{jid}.log").open("w", encoding="utf-8", errors="replace") as out:
        proc = subprocess.Popen([_python(), "-m", "paf", *args], stdout=out, stderr=subprocess.STDOUT,
                                env={**_env(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}, **flags)
        meta["pid"] = proc.pid
        save()
        if on_start:
            on_start(jid)
        while proc.poll() is None:
            time.sleep(2)
            if should_stop and should_stop():
                proc.terminate()
                proc.wait()
                meta["status"] = "stopped"
                save()
                return jid, "stopped"
    meta["status"] = "done" if proc.returncode == 0 else f"failed (exit {proc.returncode})"
    save()
    log(f"{' '.join(args[:2])}: {meta['status']}")
    return jid, "done" if proc.returncode == 0 else "failed"


def run_dir(jid: str) -> Path | None:
    """The run folder a finished job wrote its result in (its `Runs:` line)."""
    from paf.workshop_views import run_dir as from_log

    p = data_dir() / "web" / f"job-{jid}.log"
    return from_log(p.read_text(encoding="utf-8", errors="replace")) if p.is_file() else None
