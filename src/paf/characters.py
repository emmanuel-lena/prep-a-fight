"""Your characters: one /simc export per character, kept in <data>/profiles/chars/<name>-<class>.simc.

The active one is copied to profiles/current.simc (what the preps read), and the analyzed spec follows it. Pasting
the export of a character already known updates it. A character found on Warcraft Logs (paf.character) is kept the
same way, marked as imported: it has no bags.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from paf.config import data_dir

IMPORTED = "# prep-a-fight: imported from Warcraft Logs (no bags)"


@dataclass
class Character:
    slug: str
    name: str
    class_name: str
    spec: str
    bags: int  # items in the bags (0: no Top Gear)
    imported: bool  # read from a log, not a /simc export
    mtime: float
    current: bool


def _dir() -> Path:
    return data_dir() / "profiles" / "chars"


def _current() -> Path:
    return data_dir() / "profiles" / "current.simc"


def slug(name: str, class_name: str) -> str:
    s = re.sub(r"[^\w]+", "-", f"{name}-{class_name}".lower(), flags=re.UNICODE).strip("-")
    return s or "character"


def _read(p: Path):
    from paf.profile import parse_simc_export

    return parse_simc_export(p.read_text(encoding="utf-8-sig"))


def _migrate() -> None:
    """A profile loaded before the characters existed becomes the first character."""
    cur = _current()
    if cur.is_file() and not (_dir().is_dir() and any(_dir().glob("*.simc"))):
        prof = _read(cur)
        if prof.class_name:
            _dir().mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cur, _dir() / f"{slug(prof.name, prof.class_name)}.simc")


def current_slug() -> str:
    cur = _current()
    if not cur.is_file():
        return ""
    prof = _read(cur)
    return slug(prof.name, prof.class_name) if prof.class_name else ""


def all_characters() -> list[Character]:
    _migrate()
    now = current_slug()
    out = []
    for p in sorted(_dir().glob("*.simc"), key=lambda p: -p.stat().st_mtime) if _dir().is_dir() else []:
        text = p.read_text(encoding="utf-8-sig")
        prof = _read(p)
        if not prof.class_name:
            continue
        out.append(Character(p.stem, prof.name, prof.class_name, prof.spec, len(prof.candidates),
                             IMPORTED in text, p.stat().st_mtime, p.stem == now))
    return sorted(out, key=lambda c: (not c.current, -c.mtime))


def save(text: str, imported: bool = False) -> Character:
    """Keep this export (new character, or an update of a known one) and make it the active character."""
    from paf.profile import parse_simc_export

    text = text.replace("\r\n", "\n")
    if imported and IMPORTED not in text:
        text = IMPORTED + "\n" + text
    prof = parse_simc_export(text)
    if not prof.class_name:
        raise ValueError("not a /simc export")
    _migrate()
    _dir().mkdir(parents=True, exist_ok=True)
    s = slug(prof.name, prof.class_name)
    (_dir() / f"{s}.simc").write_text(text, encoding="utf-8")
    select(s)
    return next(c for c in all_characters() if c.slug == s)


def select(s: str) -> bool:
    """Make a known character the active one (its spec becomes the analyzed spec)."""
    from paf.profile import use_profile_spec

    p = _dir() / f"{s}.simc"
    if not re.fullmatch(r"[\w-]+", s) or not p.is_file():
        return False
    _current().parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, _current())
    use_profile_spec(_read(p))
    return True


def remove(s: str) -> bool:
    p = _dir() / f"{s}.simc"
    if not re.fullmatch(r"[\w-]+", s) or not p.is_file():
        return False
    p.unlink()
    if current_slug() == s:  # the active one: the next one takes its place, or none
        rest = all_characters()
        if rest:
            select(rest[0].slug)
        else:
            _current().unlink(missing_ok=True)
    return True


def is_imported(profile_text: str) -> bool:
    return IMPORTED in profile_text
