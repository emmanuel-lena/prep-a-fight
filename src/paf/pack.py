"""Prep packs: what a prep computes from the top players' logs, without the logs.

A pack holds the rebuilt fight, its validation, the top players' cooldown timings (ranks only), their talent
builds (string + count), the mechanics / actions stats and the add data of the raid planner. No player name, no
report code, no position, no raw event: only our own computed numbers, so it can be shared (issue #6). JSON only,
so a downloaded pack can never run code.

A pack lasts a week: it is stale once the weekly reset of the player's region has passed since it was made (the top
kills and rankings move mostly at the reset), and the next prep refreshes it; `paf prep --refresh` forces it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from paf.actions import Action
from paf.assigns import Mechanic
from paf.config import data_dir
from paf.corpus.timeline import Ability, Timeline
from paf.defensives import DefensiveMoment, Defensives
from paf.fight import Fight
from paf.raidneed import AddType
from paf.talent_sim import Build

VERSION = 1
# weekly reset per region, in UTC (weekday: Monday = 0). To check against Blizzard's announcements: EU Wednesday
# morning, NA Tuesday, Asia Thursday morning local time (Wednesday evening UTC).
RESETS = {"eu": (2, 4), "us": (1, 15), "kr": (2, 23), "tw": (2, 23), "cn": (2, 23)}


@dataclass
class PackData:
    encounter_id: int
    difficulty: int
    class_name: str  # Warcraft Logs class ("Shaman")
    spec: str  # Warcraft Logs spec ("Elemental")
    created: str  # ISO 8601 UTC
    kills: int
    boss: str  # the unit taking most of the damage
    fight: Fight  # rebuilt fight, movement scale from the validation, add scale 1 (calibrated per player)
    phases: list[tuple[str, float]] = field(default_factory=list)  # name, median start
    add_share_spec: float | None = None  # median share of the spec's damage on adds
    moving_share: float = 0.0
    boss_share: float | None = None  # top players' share of damage on the boss (calibration target)
    validation: tuple[float, float, float] | None = None  # simulated / real DPS of the tops: min, median, max
    timeline: Timeline | None = None  # top 25
    timeline_all: Timeline | None = None
    builds: list[Build] = field(default_factory=list)
    add_types: list[AddType] = field(default_factory=list)
    mechanics: list[Mechanic] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    defensives: Defensives | None = None  # when the top players press their defensives
    # how much the top players cast and move (paf.review.tops_activity): busy, moving, [(busy, moving) per phase]
    activity: tuple | None = None
    version: int = VERSION


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def region() -> str:
    """The player's region (the rankings' region setting, else the guild's), for its weekly reset."""
    from paf import settings

    r = (settings.get("region") or settings.get("guild_region") or "eu").lower()
    return r if r in RESETS else "eu"


def last_refresh(now: datetime | None = None, where: str | None = None) -> datetime:
    """The last weekly reset of the region (an aware UTC datetime)."""
    day, hour = RESETS.get((where or region()).lower(), RESETS["eu"])
    now = (now or datetime.now(UTC)).astimezone(UTC)
    cut = (now - timedelta(days=(now.weekday() - day) % 7)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return cut if now >= cut else cut - timedelta(days=7)


def is_stale(created: str, now: datetime | None = None, where: str | None = None) -> bool:
    try:
        made = datetime.fromisoformat(created)
    except ValueError:
        return True
    if made.tzinfo is None:
        made = made.replace(tzinfo=UTC)
    return made < last_refresh(now, where)


# --- JSON ----------------------------------------------------------------------------------------

def _timeline_to(tl: Timeline | None) -> dict | None:
    if tl is None:
        return None
    d = asdict(tl)
    for p in d["players"]:
        p["casts"] = {str(k): v for k, v in p.get("casts", {}).items()}
        p.pop("report", None)
        p.pop("name", None)
    return d


def _timeline_from(d: dict | None) -> Timeline | None:
    if d is None:
        return None
    d = dict(d)
    d["abilities"] = [Ability(**a) for a in d.get("abilities", [])]
    d["phases"] = [tuple(p) for p in d.get("phases", [])]
    d["waves"] = [tuple(w) for w in d.get("waves", [])]
    d["boss_casts"] = [(n, list(ts)) for n, ts in d.get("boss_casts", [])]
    players = []
    for p in d.get("players", []):
        p = dict(p)
        p["casts"] = {int(k): v for k, v in p.get("casts", {}).items()}
        if "targets" in p:
            p["targets"] = [tuple(x) for x in p["targets"]]
        players.append(p)
    d["players"] = players
    return Timeline(**d)


def to_json(p: PackData) -> str:
    d = asdict(replace(p, builds=[]))  # builds from the corpus carry its rows: written below without them
    d["fight"] = asdict(p.fight)
    d["timeline"], d["timeline_all"] = _timeline_to(p.timeline), _timeline_to(p.timeline_all)
    d["builds"] = [{"key": sorted(b.key), "code": b.code, "label": b.label, "n": b.count, "rank": b.median_rank}
                   for b in p.builds]
    d["add_types"] = [{**asdict(t), "estimated": sorted(t.estimated)} for t in p.add_types]
    return json.dumps(d, separators=(",", ":"))


def from_json(text: str) -> PackData:
    d = json.loads(text)
    if d.get("version") != VERSION:
        raise ValueError(f"pack version {d.get('version')} (this app reads {VERSION})")
    d["fight"] = Fight.from_dict(d["fight"])
    d["phases"] = [tuple(x) for x in d.get("phases", [])]
    if d.get("validation") is not None:
        d["validation"] = tuple(d["validation"])
    d["timeline"], d["timeline_all"] = _timeline_from(d.get("timeline")), _timeline_from(d.get("timeline_all"))
    d["builds"] = [Build(frozenset(b["key"]), [], b.get("code"), b.get("label", ""), int(b.get("n", 0)),
                         float(b.get("rank", 0.0)))
                   for b in d.get("builds", [])]
    d["add_types"] = [AddType(**{**t, "estimated": set(t.get("estimated", []))}) for t in d.get("add_types", [])]
    d["mechanics"] = [Mechanic(**m) for m in d.get("mechanics", [])]
    d["actions"] = [Action(**a) for a in d.get("actions", [])]
    if d.get("defensives"):
        df = d["defensives"]
        d["defensives"] = Defensives(
            [DefensiveMoment(m["time"], m["share"], [tuple(s) for s in m["spells"]], m["boss_ability"],
                             m["boss_spell_id"]) for m in df.get("moments", [])],
            [tuple(u) for u in df.get("usage", [])], df.get("kills", 0))
    if d.get("activity"):
        a = d["activity"]
        d["activity"] = (a[0], a[1], [tuple(x) for x in a[2]])
    return PackData(**d)


# --- local store -----------------------------------------------------------------------------------

def key(encounter_id: int, difficulty: int, class_name: str, spec: str) -> str:
    return f"{class_name}-{spec}/{encounter_id}-{difficulty}".lower()


def local_path(encounter_id: int, difficulty: int, class_name: str, spec: str) -> Path:
    return data_dir() / "packs" / f"{key(encounter_id, difficulty, class_name, spec)}.json"


def save(p: PackData) -> Path:
    path = local_path(p.encounter_id, p.difficulty, p.class_name, p.spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(p), encoding="utf-8")
    return path


def load(encounter_id: int, difficulty: int, class_name: str, spec: str) -> PackData | None:
    path = local_path(encounter_id, difficulty, class_name, spec)
    if not path.is_file():
        return None
    try:
        return from_json(path.read_text(encoding="utf-8"))
    except (ValueError, KeyError, TypeError):
        return None


# --- shared packs (the relay, tools/feedback-worker) ---------------------------------------------

def relay() -> str:
    """The relay URL the installer was built with ('' without one: packs stay on this computer)."""
    from paf.feedback import endpoint, is_discord

    url = endpoint()
    return "" if not url or is_discord(url) else url.rstrip("/")


def _request(url: str, data: bytes | None = None, method: str = "GET"):
    import urllib.request

    from paf import __version__

    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": f"prep-a-fight/{__version__}", "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=30)


def fetch_shared(encounter_id: int, difficulty: int, class_name: str, spec: str) -> PackData | None:
    """The shared pack of this spec, boss and difficulty, if the relay has one (saved locally too)."""
    import urllib.error

    base = relay()
    if not base:
        return None
    try:
        with _request(f"{base}/packs/{key(encounter_id, difficulty, class_name, spec)}") as resp:
            p = from_json(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    save(p)
    return p


def publish(p: PackData) -> str:
    """Share a pack made from the logs; returns what happened, in a few words."""
    import urllib.error

    base = relay()
    if not base:
        return "not shared (no relay in this build)"
    try:
        with _request(f"{base}/packs/{key(p.encounter_id, p.difficulty, p.class_name, p.spec)}",
                      to_json(p).encode("utf-8"), "PUT"):
            return "shared with the other players"
    except urllib.error.HTTPError as ex:
        return f"not shared: {ex.read().decode('utf-8', 'replace')[:120] or ex.code}"
    except OSError as ex:
        return f"not shared: {ex}"
