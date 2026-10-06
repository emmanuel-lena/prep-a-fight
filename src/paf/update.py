"""Update from the app: is a newer release out on GitHub, and install it (installed copies only).

The check reads the public releases of the repository (no account, no token), at most once a day. The update
downloads the release's installer over HTTPS, checks its size and SHA-256 against what GitHub publishes for the
asset, then runs it silently over this install folder; the installer relaunches the app.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from paf import __version__
from paf.config import INSTALL_MARKER, data_dir

RELEASES = "https://api.github.com/repos/emmanuel-lena/prep-a-fight/releases?per_page=10"
CHECK_EVERY = 24 * 3600


@dataclass
class Release:
    version: str
    url: str  # the release page (what's new)
    notes: str
    asset: str  # installer download URL
    size: int
    sha256: str  # "" when GitHub does not publish it


def parse_version(v: str) -> tuple[int, ...]:
    out = []
    for part in v.lstrip("v").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def install_dir() -> Path | None:
    """The folder of a copy made by the Windows installer (one-click update possible), else None."""
    folder = Path(sys.prefix).parent
    return folder if (folder / INSTALL_MARKER).is_file() and (folder / "unins000.exe").is_file() else None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"prep-a-fight/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def parse_releases(data: list[dict]) -> Release | None:
    """The newest published release that has an installer."""
    best = None
    for r in data:
        if r.get("draft"):
            continue
        asset = next((a for a in r.get("assets") or [] if str(a.get("name", "")).endswith(".exe")), None)
        if asset is None:
            continue
        rel = Release(str(r.get("tag_name", "")).lstrip("v"), r.get("html_url", ""), r.get("body") or "",
                      asset.get("browser_download_url", ""), int(asset.get("size") or 0),
                      str(asset.get("digest") or "").removeprefix("sha256:"))
        if best is None or parse_version(rel.version) > parse_version(best.version):
            best = rel
    return best


def available(force: bool = False) -> Release | None:
    """A release newer than this version, from a check made at most once a day (cached on disk)."""
    cache = data_dir() / "web" / "update.json"
    data = None
    if not force and cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() - saved.get("at", 0) < CHECK_EVERY:
                data = saved["releases"]
        except (ValueError, KeyError):
            data = None
    if data is None:
        try:
            data = json.loads(_get(RELEASES))
        except (OSError, ValueError):
            return None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"at": time.time(), "releases": data}), encoding="utf-8")
    rel = parse_releases(data if isinstance(data, list) else [])
    return rel if rel and parse_version(rel.version) > parse_version(__version__) else None


def download(rel: Release) -> Path:
    """The installer of ``rel``, checked (size, SHA-256 when published)."""
    if not rel.asset.startswith("https://github.com/"):  # GitHub then redirects to its download host
        raise ValueError(f"unexpected download host: {rel.asset}")
    blob = _get(rel.asset)
    if rel.size and len(blob) != rel.size:
        raise ValueError(f"download incomplete ({len(blob)} of {rel.size} bytes)")
    if rel.sha256 and hashlib.sha256(blob).hexdigest() != rel.sha256.lower():
        raise ValueError("the downloaded installer does not match the release's checksum")
    out = data_dir() / "updates" / f"prep-a-fight-setup-{rel.version}.exe"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    return out


def run_installer(setup: Path, folder: Path) -> None:
    """Start the installer over this install, detached; it closes nothing itself (the app quits right after)
    and relaunches the app when done."""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={folder}", "/RELAUNCH=1"],
                     creationflags=flags, close_fds=True)


STATE: dict = {"release": None}


def check_in_background() -> None:
    """At launch: look for a newer release without slowing the app down; the pages read STATE."""
    import threading

    from paf import settings

    if settings.get("check_updates") != "on":
        return

    def run() -> None:
        STATE["release"] = available()

    threading.Thread(target=run, daemon=True).start()
