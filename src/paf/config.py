"""Paths and settings: user data directory, .env loading."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Where paf keeps downloaded tools and caches (override with PAF_HOME)."""
    env = os.environ.get("PAF_HOME")
    return Path(env) if env else Path.home() / ".paf"


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE lines, # comments. Existing env vars win."""
    path = path or Path.cwd() / ".env"
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
