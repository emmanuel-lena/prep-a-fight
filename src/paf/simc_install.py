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
            if total:
                print(f"\r  {done / total:6.1%}  {done >> 20} / {total >> 20} MiB", end="", flush=True)
    print()
    tmp.replace(dest)


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
    if root.is_dir():
        candidates.extend(sorted(root.glob("**/simc.exe")) + sorted(root.glob("**/simc")))
    if which := shutil.which("simc"):
        candidates.append(Path(which))
    for c in candidates:
        if c.is_file():
            return c
    return None


def install_nightly(force: bool = False) -> Path:
    """Download the latest Windows nightly into <data_dir>/simc/<version>/ and return simc.exe."""
    if sys.platform != "win32":
        raise RuntimeError(
            "Automatic install is Windows-only for now. On Linux/macOS use the official Docker image "
            "(simulationcraftorg/simc) or build simc, then pass --simc or set PAF_SIMC."
        )
    import py7zr  # local import: only needed here

    build = latest_build(parse_nightly_index(_get(NIGHTLY_INDEX).decode("utf-8", "replace")), windows_arch())
    target = simc_root() / build.version
    existing = next(target.glob("**/simc.exe"), None) if target.is_dir() else None
    if existing and not force:
        print(f"simc {build.version} already installed: {existing}")
        return existing

    target.mkdir(parents=True, exist_ok=True)
    archive = target / build.filename
    print(f"Downloading {build.url}")
    _download(build.url, archive)
    print("Extracting...")
    with py7zr.SevenZipFile(archive, "r") as z:
        z.extractall(target)
    archive.unlink()
    exe = next(target.glob("**/simc.exe"), None)
    if exe is None:
        raise RuntimeError(f"simc.exe not found after extracting {build.filename}")
    return exe
