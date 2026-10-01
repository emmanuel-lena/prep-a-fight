"""Paths and settings: user data directory, .env loading."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Where paf keeps downloaded tools and caches (override with PAF_HOME)."""
    env = os.environ.get("PAF_HOME")
    return Path(env) if env else Path.home() / ".paf"


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
