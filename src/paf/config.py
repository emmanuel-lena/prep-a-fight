"""Paths and settings: user data directory, .env loading."""

from __future__ import annotations

import os
import sys
from functools import cache
from pathlib import Path

INSTALL_MARKER = "paf-home.txt"  # written by the Windows installer next to its python folder


@cache
def installed_home() -> Path | None:
    """The data folder of a copy made by the Windows installer: inside the folder the player chose (the marker
    names it, relative to the install folder), unless that folder is not writable (e.g. Program Files)."""
    marker = Path(sys.prefix).parent / INSTALL_MARKER
    if not marker.is_file():
        return None
    home = marker.parent / (marker.read_text(encoding="utf-8").strip() or "data")
    try:
        home.mkdir(parents=True, exist_ok=True)
        (home / ".write-test").touch()
        (home / ".write-test").unlink()
    except OSError:
        return None
    return home


def data_dir() -> Path:
    """Where paf keeps downloaded tools and caches: PAF_HOME, else the installed copy's folder, else ~/.paf."""
    env = os.environ.get("PAF_HOME")
    if env:
        return Path(env)
    return installed_home() or Path.home() / ".paf"


# what moves from ~/.paf to the install folder (simc, caches and run folders are rebuilt or not needed)
MIGRATED = (".env", "settings.json", "profiles", "reports", "fights", "web", "gamedata", "cache")


def migrate_old_home() -> list[str]:
    """An installed copy keeps its data in its own folder; earlier versions used ~/.paf. Moves the player's
    data (credentials, settings, preps, corpus, caches) once, then deletes what is left of ~/.paf."""
    import shutil

    new, old = installed_home(), Path.home() / ".paf"
    if os.environ.get("PAF_HOME") or new is None or not old.is_dir() or new.resolve() == old.resolve():
        return []
    moved = []
    for item in sorted(old.iterdir()):
        if item.name in MIGRATED or (item.name.startswith("corpus") and item.suffix == ".sqlite"):
            if not (new / item.name).exists():
                shutil.move(str(item), str(new / item.name))
                moved.append(item.name)
    if not (old / ".env").exists():  # keep ~/.paf if anything failed to move
        shutil.rmtree(old, ignore_errors=True)
    return moved


def env_file() -> Path:
    """Where `paf serve` saves the Warcraft Logs credentials of an installed copy."""
    return data_dir() / ".env"


def save_credentials(client_id: str, client_secret: str) -> Path:
    p = env_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"WCL_CLIENT_ID={client_id.strip()}\nWCL_CLIENT_SECRET={client_secret.strip()}\n", encoding="utf-8")
    os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"] = client_id.strip(), client_secret.strip()
    return p


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE lines, # comments. Existing env vars win. Without a path: the .env of
    the current folder (a source checkout), then the one in the data directory (an installed copy)."""
    if path is None:
        return {**load_dotenv(env_file()), **load_dotenv(Path.cwd() / ".env")}
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded
