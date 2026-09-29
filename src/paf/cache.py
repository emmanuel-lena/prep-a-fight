"""Disk caches with a size cap: Warcraft Logs responses and simc results, under <data_dir>/cache.

The oldest files (by modification time) are removed first once a cache grows past its cap
(``paf config cache_max_mb``). A sim result is touched when reused, so it counts as recent.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from paf.config import data_dir


def cache_root() -> Path:
    return data_dir() / "cache"


def max_bytes() -> int:
    from paf import settings
    return int(settings.get("cache_max_mb")) * 1024 * 1024


def size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0


def prune(path: Path, limit: int) -> int:
    """Delete the oldest files until the directory fits in ``limit`` bytes; returns the bytes freed."""
    if not path.is_dir():
        return 0
    files = sorted((f for f in path.rglob("*") if f.is_file()), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    freed = 0
    for f in files:
        if total - freed <= limit:
            break
        n = f.stat().st_size
        f.unlink(missing_ok=True)
        freed += n
    for d in sorted((d for d in path.rglob("*") if d.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return freed


def prune_all(limit: int | None = None) -> dict[str, int]:
    """Cap each cache: sims get half of the budget, WCL responses the other half."""
    limit = max_bytes() if limit is None else limit
    root = cache_root()
    return {"sims": prune(root / "sims", limit // 2), "wcl": prune(root / "wcl", limit // 2)}


def clear(name: str | None = None) -> None:
    root = cache_root()
    for d in ([root / name] if name else [root / "sims", root / "wcl"]):
        shutil.rmtree(d, ignore_errors=True)


# --- simc results ---------------------------------------------------------------------------------

def sim_key(exe: Path, input_text: str, args: list[str]) -> str:
    """Same simc binary, same input and same options -> same result (up to the random seed)."""
    h = hashlib.sha256()
    st = exe.stat()
    h.update(f"{exe.resolve()}|{st.st_size}|{int(st.st_mtime)}\n".encode())
    h.update(input_text.encode())
    h.update("\n".join(args).encode())
    return h.hexdigest()


def sim_get(key: str) -> Path | None:
    p = cache_root() / "sims" / key[:2] / f"{key}.json"
    if not p.is_file():
        return None
    p.touch()
    return p


def sim_put(key: str, json_path: Path) -> None:
    p = cache_root() / "sims" / key[:2] / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(json_path, p)
