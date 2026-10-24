"""Run summaries, opt-in (the owner, 2026-10-25: "can't we log this kind of thing automatically?"): at the end of each
prep or tool run from the app, when the player turned it on in Settings, a short summary goes to the maintainers'
channel: the version, the machine (CPU, cores, memory), the command and its outcome, how long each step took (Top
Gear's passes too) and the error's traceback if it failed. Never a character, a guild, a report code or a path: the
log's lines are not sent, only these measures (paf.feedback.scrub on top).

Where it goes: a Discord webhook built into the installer (``telemetry_url.txt`` next to this file, written by
tools/build-installer.ps1 from the PAF_TELEMETRY_URL secret, never committed). Without it nothing is sent."""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from paf import settings

URL_FILE = Path(__file__).parent / "telemetry_url.txt"
SAFE_ARGS = re.compile(r"^--?[a-z][a-z0-9-]*$")  # an option's name; its value may be personal (a profile, a log)
PASS_LINE = re.compile(r"^(Pass \d.*|  kept: .*|  [\w .-]+: \d+s)$", re.M)  # Top Gear's passes and their times
TRACEBACK = re.compile(r"Traceback \(most recent call last\):\n(?:.*\n)*?\S.*(?:Error|Exception|Exit)[^\n]*")


def endpoint() -> str:
    url = os.environ.get("PAF_TELEMETRY_URL", "")
    if not url and URL_FILE.is_file():
        url = URL_FILE.read_text(encoding="utf-8").strip()
    return url if url.startswith("https://") else ""


def enabled() -> bool:
    return settings.get("telemetry") == "on" and bool(endpoint())


def command(args: list[str]) -> str:
    """The command and its options' names: `prep --difficulty --profile`, no boss name, profile or log."""
    if not args:
        return ""
    return " ".join([args[0], *(a for a in args[1:] if SAFE_ARGS.match(a))])


def summary(args: list[str], status: str, log: str, seconds: float) -> tuple[str, str]:
    """(title, body) of one run's summary: measures only."""
    from paf.feedback import performance, scrub, system_line

    perf = performance(log)
    passes = "\n".join(m.group(0) for m in PASS_LINE.finditer(log))
    tb = TRACEBACK.search(log)
    body = (f"{system_line()}\nCommand: paf {command(args)}\nOutcome: {status} in {seconds:.0f} s\n\n{perf}\n"
            + (f"\nTop Gear passes:\n{passes}\n" if passes else "")
            + (f"\n--- error ---\n{tb.group(0)[-3000:]}\n" if tb and not status.startswith("done") else ""))
    title = f"[run] {args[0] if args else '?'} {status.split(' ')[0]}"
    return title, scrub(body)


def after_job(args: list[str], status: str, log_path: Path, started: float) -> None:
    """Send the summary of a finished job in the background (never slows the app, never fails it)."""
    if not enabled() or status == "paused":
        return

    def send() -> None:
        try:
            from paf.feedback import send as post

            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            title, body = summary(args, status, log, time.time() - started)
            post(endpoint(), title, body)
        except Exception:  # noqa: BLE001 - a measure, never a failure
            pass
    threading.Thread(target=send, daemon=True).start()
