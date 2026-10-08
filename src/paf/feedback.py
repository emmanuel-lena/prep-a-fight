"""Feedback from the app: the player's message plus the log of a prep (or the app's log), cleaned of anything
personal to the computer, sent to the maintainers.

Where it goes: a Discord webhook when the installer was built with one (``feedback_url.txt`` next to this file,
written by tools/build-installer.ps1 from the PAF_FEEDBACK_WEBHOOK secret, never committed); otherwise a GitHub issue
form, pre-filled, opened in the browser. Nothing is ever sent without the player clicking Send on a preview.
"""

from __future__ import annotations

import json
import os
import platform
import re
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from paf import __version__
from paf.config import data_dir

ISSUES = "https://github.com/emmanuel-lena/prep-a-fight/issues/new"
WEBHOOK_FILE = Path(__file__).parent / "feedback_url.txt"
MAX_LOG = 60_000  # characters of log kept (the end of it: where things fail)


def endpoint() -> str:
    url = os.environ.get("PAF_FEEDBACK_URL", "")
    if not url and WEBHOOK_FILE.is_file():
        url = WEBHOOK_FILE.read_text(encoding="utf-8").strip()
    return url if url.startswith("https://") else ""


def is_discord(url: str) -> bool:
    return url.startswith("https://discord.com/api/webhooks/")


def send(url: str, title: str, body: str) -> str:
    """Send to the configured endpoint; returns the link of the created issue ('' for Discord)."""
    if is_discord(url):
        send_discord(url, title, body)
        return ""
    req = urllib.request.Request(url, data=json.dumps({"title": title, "body": body, "version": __version__}).encode(),
                                 method="POST", headers={"Content-Type": "application/json",
                                                         "User-Agent": f"prep-a-fight/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return str(json.loads(resp.read() or b"{}").get("url", ""))


def scrub(text: str) -> str:
    """Remove what identifies the computer or gives access: the Warcraft Logs key, user folders, emails."""
    for name in ("WCL_CLIENT_SECRET", "WCL_CLIENT_ID"):
        value = os.environ.get(name, "")
        if len(value) >= 6:
            text = text.replace(value, f"<{name}>")
    text = re.sub(r"(?im)^.*(client_secret|WCL_CLIENT_SECRET|access_token).*$", "<line removed>", text)
    for path, label in ((str(data_dir()), "<data>"), (str(Path.home()), "<home>")):
        text = text.replace(path, label).replace(path.replace("\\", "/"), label)
    text = re.sub(r"(?i)[A-Z]:\\Users\\[^\\\s\"']+", "<home>", text)
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", text)


def system_line() -> str:
    return f"prep-a-fight {__version__} · {platform.system()} {platform.release()} · Python {platform.python_version()}"


def job_log(jid: str) -> tuple[str, str]:
    """(what the job ran, its log) of a prep or a tool started from the app."""
    folder = data_dir() / "web"
    meta = folder / f"job-{jid}.json"
    args = " ".join(json.loads(meta.read_text(encoding="utf-8")).get("args", [])) if meta.is_file() else ""
    log = folder / f"job-{jid}.log"
    return args, log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""


def app_log() -> str:
    p = data_dir() / "web" / "app.log"
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def _memory_gb() -> float | None:
    if platform.system() != "Windows":
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
        except (ValueError, OSError, AttributeError):
            return None
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                    ("page_avail", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                    ("virtual_avail", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]
    st = Status()
    st.length = ctypes.sizeof(Status)
    return st.total / 2**30 if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)) else None


STEP_LINE = re.compile(r"^== (.+?)\s+\[\+(\d+)s\]", re.M)


def performance(log: str = "") -> str:
    """Measures to make the app faster on players' computers, nothing personal: the machine (CPU, cores, memory),
    the simc version, the collection settings, the duration of each step of the prep reported (its log's step lines
    and quota waits) and the median of each step over the last preps."""
    import statistics as st

    from paf import settings

    lines = [f"CPU: {_cpu_name()} · {os.cpu_count()} logical cores"
             + (f" · {mem:.0f} GB memory" if (mem := _memory_gb()) else "")]
    try:
        from paf.simc_install import find_simc

        exe = find_simc()
        lines.append(f"simc: {exe.parent.name if exe else 'not installed'}")
    except Exception:  # noqa: BLE001 - a measure, never a failure
        pass
    lines.append(f"settings: corpus_size {settings.get('corpus_size')} · corpus_points {settings.get('corpus_points')}")
    steps = [(m.group(1), int(m.group(2))) for m in STEP_LINE.finditer(log or "")]
    if steps:
        ends = [t for _, t in steps[1:]] + [None]
        rows = []
        for (name, t0), t1 in zip(steps, ends, strict=True):
            if name.startswith("Done"):  # the end mark, not a step
                continue
            name = re.sub(r"\d[\d,]*", "#", name)[:48]  # step names only, their numbers (kills, items) masked
            rows.append(f"  {name}: {'running' if t1 is None else f'{t1 - t0} s'}")
        lines.append("this prep, step by step:\n" + "\n".join(rows))
        lines.append(f"this prep: {steps[-1][1]} s to its last step, {log.count('quota used up')} quota waits")
    try:
        from paf.progress import history

        hist = history()
        if hist:
            lines.append("last preps, median per step: " + ", ".join(
                f"{k} {st.median(v):.0f} s" for k, v in sorted(hist.items(), key=lambda x: -st.median(x[1])) if v))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


def report(message: str, what: str, log: str, perf: str = "") -> tuple[str, str]:
    """(title, body) of the feedback, scrubbed, log cut to its end; perf: performance() to attach."""
    log = scrub(log)[-MAX_LOG:]
    title = (message.strip().splitlines() or ["Feedback"])[0][:80]
    body = f"{message.strip()}\n\n{system_line()}\n" + (f"Command: paf {scrub(what)}\n" if what else "")
    if perf:
        body += f"\n--- performance ---\n{scrub(perf)}\n"
    return title, body + (f"\n--- log (end) ---\n{log}" if log else "")


def send_discord(url: str, title: str, body: str) -> None:
    """The message as a Discord post, the full text attached as a file (posts are capped at 2000 characters)."""
    head = body.split("\n--- log", 1)[0]
    payload = json.dumps({"content": f"**{title}**\n{head}"[:1900], "allowed_mentions": {"parse": []}})
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'
        f"{payload}\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="feedback.txt"\r\n'
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n",
        f"--{boundary}--\r\n",
    ]
    req = urllib.request.Request(url, data="".join(parts).encode("utf-8"), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "User-Agent": f"prep-a-fight/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def issue_url(title: str, body: str) -> str:
    """A pre-filled GitHub issue (URLs stay under ~8 KB: the log is cut to its end)."""
    room = 3000  # characters before percent-encoding, which can triple them
    if len(body) > room:
        body = body[:1500] + "\n[...]\n" + body[-(room - 1500):]
    return ISSUES + "?" + urllib.parse.urlencode({"title": title, "body": body, "labels": "beta"})
