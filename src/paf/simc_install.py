"""Download and locate the SimulationCraft command-line binary.

Nightlies are published at downloads.simulationcraft.org/nightly/ as
``simc-<version>.<build>.<commit>-win64.7z``. That host only serves valid
certificates over plain HTTP, so the download is not TLS-protected.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from paf.config import data_dir

NIGHTLY_INDEX = "http://downloads.simulationcraft.org/nightly/?C=M;O=D"
NIGHTLY_BASE = "http://downloads.simulationcraft.org/nightly/"
USER_AGENT = "prep-a-fight (+https://github.com/emmanuel-lena/prep-a-fight)"

_HREF = re.compile(r'href="(simc-[^"/]+?-(win64|winarm64)\.7z)"')


@dataclass(frozen=True)
class NightlyBuild:
    filename: str
    arch: str  # "win64" or "winarm64"

    @property
    def url(self) -> str:
        return NIGHTLY_BASE + self.filename

    @property
    def version(self) -> str:
        # simc-1210.01.4c7c736-win64.7z -> 1210.01.4c7c736
        return self.filename.removeprefix("simc-").rsplit("-", 1)[0]


def parse_nightly_index(html: str) -> list[NightlyBuild]:
    """Windows builds in page order (the index is requested newest first)."""
    return [NightlyBuild(m.group(1), m.group(2)) for m in _HREF.finditer(html)]


def windows_arch() -> str:
    return "winarm64" if platform.machine().lower() in ("arm64", "aarch64") else "win64"


def latest_build(builds: list[NightlyBuild], arch: str) -> NightlyBuild:
    for b in builds:
        if b.arch == arch:
            return b
    raise LookupError(f"no {arch} build found in the nightly index")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            _beat()
            if total:
                print(f"\r  {done / total:6.1%}  {done >> 20} / {total >> 20} MiB", end="", flush=True)
    print()
    tmp.replace(dest)


PARTIAL = ".partial"  # a version folder being extracted


def simc_root() -> Path:
    return data_dir() / "simc"


def find_simc(explicit: str | None = None) -> Path | None:
    """--simc flag, then PAF_SIMC, then the installed nightly, then PATH."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if env := os.environ.get("PAF_SIMC"):
        candidates.append(Path(env))
    root = simc_root()
    if root.is_dir():  # the newest install first (version folders do not sort by name: they end in a commit hash)
        newest = sorted((d for d in root.iterdir() if d.is_dir() and not d.name.endswith(PARTIAL)),
                        key=lambda d: d.stat().st_mtime, reverse=True)
        candidates.extend(exe for d in newest for name in ("simc.exe", "simc")
                          for exe in sorted(d.glob(f"**/{name}")))
    if which := shutil.which("simc"):
        candidates.append(Path(which))
    for c in candidates:
        if c.is_file():
            return c
    return None


def bundled_profile(pattern: str = "*_Shaman_Elemental.simc", simc: str | None = None) -> Path | None:
    """A reference profile shipped with simc (newest tier folder first), e.g. MID2_Shaman_Elemental."""
    exe = find_simc(simc)
    if exe is None:
        return None
    hits = sorted((exe.parent / "profiles").glob(f"*/{pattern}"), reverse=True)
    return hits[0] if hits else None


def install_nightly(force: bool = False) -> Path:
    """Download the latest Windows nightly into <data_dir>/simc/<version>/ and return simc.exe."""
    if sys.platform != "win32":
        raise RuntimeError(
            "Automatic install is Windows-only for now. On Linux/macOS use the official Docker image "
            "(simulationcraftorg/simc) or build simc, then pass --simc or set PAF_SIMC."
        )
    build = latest_build(parse_nightly_index(_get(NIGHTLY_INDEX).decode("utf-8", "replace")), windows_arch())
    target = simc_root() / build.version
    existing = next(target.glob("**/simc.exe"), None) if target.is_dir() else None
    if existing and not force:
        print(f"simc {build.version} already installed: {existing}")
        return existing

    simc_root().mkdir(parents=True, exist_ok=True)
    lock = _lock_file()
    lock.write_text(str(os.getpid()), encoding="utf-8")
    try:
        return _install(build, target, force)
    finally:
        lock.unlink(missing_ok=True)


def _lock_file() -> Path:
    """Present while a copy of the app downloads SimulationCraft (the app and a prep must not both download)."""
    return simc_root() / ".installing"


LOCK_STALE = 120.0  # seconds: a download touches its lock all along; an older one is from a download that died


def _beat() -> None:
    try:
        _lock_file().touch(exist_ok=True)
    except OSError:
        pass


def wait_for_simc(timeout: float = 1800.0) -> Path:
    """simc for a sim about to start: the installed one, else the one the app is downloading (waited for), else
    downloaded now. A first prep on a new computer can reach its sims before the app's download ends."""
    import time

    exe = find_simc()
    if exe is not None:
        return exe
    lock, t0, said = _lock_file(), time.time(), False
    while lock.is_file() and time.time() - lock.stat().st_mtime < LOCK_STALE and time.time() - t0 < timeout:
        if not said:
            print("Waiting for SimulationCraft to finish downloading (first launch)...", flush=True)
            said = True
        time.sleep(5)
        exe = find_simc()
        if exe is not None:
            return exe
    if sys.platform != "win32":
        raise RuntimeError("simc not found: pass --simc or set PAF_SIMC")
    print("SimulationCraft is not installed yet: downloading it (about 100 MB, once)...", flush=True)
    return install_nightly()


def _install(build: NightlyBuild, target: Path, force: bool) -> Path:
    import py7zr  # local import: only needed here

    # extracted aside, renamed when complete: find_simc() never picks a half-extracted simc
    partial = target.with_name(target.name + PARTIAL)
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    archive = partial / build.filename
    print(f"Downloading {build.url}")
    _download(build.url, archive)
    print("Extracting... (a few minutes)", flush=True)
    import threading
    import time

    done = threading.Event()

    def alive() -> None:  # a sign of life in the log: the app tells a long step from a stopped prep
        t0 = time.time()
        while not done.wait(30):
            _beat()
            print(f"    still extracting ({int(time.time() - t0)} s)", flush=True)
    threading.Thread(target=alive, daemon=True).start()
    try:
        with py7zr.SevenZipFile(archive, "r") as z:
            z.extractall(partial)
    finally:
        done.set()
    archive.unlink()
    if force:
        shutil.rmtree(target, ignore_errors=True)
    if target.is_dir() and not any(target.iterdir()):
        target.rmdir()
    partial.rename(target)
    exe = next(target.glob("**/simc.exe"), None)
    if exe is None:
        raise RuntimeError(f"simc.exe not found after extracting {build.filename}")
    target.touch()  # the newest install is the one find_simc() picks
    remove_old_simc()
    return exe


def remove_old_simc() -> int:
    """Delete the SimulationCraft versions find_simc() no longer uses (about 540 MB each); returns how many."""
    exe = find_simc()
    root = simc_root()
    if exe is None or not root.is_dir() or root not in exe.parents:
        return 0
    keep = next(d for d in [exe.parent, *exe.parents] if d.parent == root)
    removed = 0
    import time

    for d in root.iterdir():
        # a folder touched in the last hour may be a download in progress (no simc.exe yet)
        if d.is_dir() and d != keep and time.time() - d.stat().st_mtime > 3600:
            shutil.rmtree(d, ignore_errors=True)  # a version still running a sim stays until next time
            removed += not d.exists()
    return removed


_BACKGROUND: dict = {"thread": None, "error": ""}


def ensure_simc() -> str:
    """For the app: '' when simc is installed; otherwise starts the download once, in the background, and
    returns 'downloading' or the error of the last attempt."""
    import threading

    if find_simc() is not None:
        return ""
    if sys.platform != "win32":
        return "SimulationCraft is not installed: pass --simc or set PAF_SIMC (automatic install is Windows-only)."
    t = _BACKGROUND["thread"]
    if t is not None and t.is_alive():
        return "downloading"
    if t is not None and _BACKGROUND["error"]:
        return _BACKGROUND["error"]

    def run() -> None:
        try:
            install_nightly()
        except Exception as exc:  # noqa: BLE001 - shown in the app, which offers a retry
            _BACKGROUND["error"] = f"SimulationCraft could not be downloaded: {exc}"

    _BACKGROUND["error"] = ""
    _BACKGROUND["thread"] = threading.Thread(target=run, daemon=True)
    _BACKGROUND["thread"].start()
    return "downloading"


def simc_status() -> str:
    """ensure_simc() without starting anything: '' when there is nothing to say."""
    t = _BACKGROUND["thread"]
    if t is None or find_simc() is not None:
        return ""
    return "downloading" if t.is_alive() else _BACKGROUND["error"]
