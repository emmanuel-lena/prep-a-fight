"""SQLite storage for the corpus. Times are seconds from the pull. No player names are stored."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from paf.config import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS fight(
  report TEXT, fight_id INT, encounter_id INT, difficulty INT, size INT,
  duration_s REAL, kill INT, avg_ilvl REAL, region TEXT, guild_id INT,
  cohort TEXT, status TEXT DEFAULT 'pending', error TEXT, fetched_at TEXT,
  PRIMARY KEY(report, fight_id));
CREATE TABLE IF NOT EXISTS ranked(            -- the analyzed spec's player in that kill
  report TEXT, fight_id INT, class TEXT, spec TEXT, rank_page INT, rank_pos INT,
  dps REAL, ilvl REAL, actor_id INT, talents_json TEXT, gear_json TEXT, pi_count INT,
  talent_code TEXT, name TEXT,               -- name is only used to find actor_id, then cleared
  PRIMARY KEY(report, fight_id));
CREATE TABLE IF NOT EXISTS phase(
  report TEXT, fight_id INT, phase_id INT, name TEXT, is_intermission INT, t_start REAL,
  PRIMARY KEY(report, fight_id, phase_id));
CREATE TABLE IF NOT EXISTS npc(game_id INT PRIMARY KEY, name TEXT, is_boss INT);
CREATE TABLE IF NOT EXISTS add_instance(
  report TEXT, fight_id INT, actor_id INT, instance INT, game_id INT,
  t_spawn REAL, t_death REAL, died INT,
  PRIMARY KEY(report, fight_id, actor_id, instance));
CREATE TABLE IF NOT EXISTS player(
  report TEXT, fight_id INT, actor_id INT, class TEXT, spec TEXT, ilvl REAL, total_damage REAL,
  PRIMARY KEY(report, fight_id, actor_id));
CREATE TABLE IF NOT EXISTS damage_by_target(
  report TEXT, fight_id INT, actor_id INT, target TEXT, amount REAL,
  PRIMARY KEY(report, fight_id, actor_id, target));
CREATE TABLE IF NOT EXISTS enemy_cast(
  report TEXT, fight_id INT, source_id INT, source_instance INT, ability_id INT, type TEXT, t REAL);
CREATE TABLE IF NOT EXISTS player_cast(
  report TEXT, fight_id INT, actor_id INT, ability_id INT, type TEXT, t REAL, x REAL, y REAL,
  facing REAL, target_id INT, target_instance INT);
CREATE TABLE IF NOT EXISTS player_buff(
  report TEXT, fight_id INT, actor_id INT, ability_id INT, type TEXT, t REAL, source_id INT);
CREATE TABLE IF NOT EXISTS ability(id INT PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS mech_event(       -- players hit by boss mechanics, and interrupts
  report TEXT, fight_id INT, kind TEXT, ability_id INT, actor_id INT, t REAL);
CREATE TABLE IF NOT EXISTS mech_status(report TEXT, fight_id INT, fetched_at TEXT, PRIMARY KEY(report, fight_id));
CREATE INDEX IF NOT EXISTS ix_me ON mech_event(report, fight_id);
CREATE TABLE IF NOT EXISTS unit_window(      -- windows when secondary boss units take damage (damage-taken graph)
  report TEXT, fight_id INT, name TEXT, t_start REAL, duration REAL, rate_ratio REAL);
CREATE TABLE IF NOT EXISTS unit_status(report TEXT, fight_id INT, PRIMARY KEY(report, fight_id));
CREATE TABLE IF NOT EXISTS boss_aura(        -- buffs/debuffs applied to the boss by enemies (possible damage amps)
  report TEXT, fight_id INT, ability_id INT, kind TEXT, t_start REAL, duration REAL, rate_ratio REAL);
CREATE TABLE IF NOT EXISTS aura_status(report TEXT, fight_id INT, PRIMARY KEY(report, fight_id));
CREATE TABLE IF NOT EXISTS phase_rate(       -- boss damage-taken rate during a phase vs the rest of the fight
  report TEXT, fight_id INT, phase_id INT, rate_ratio REAL, PRIMARY KEY(report, fight_id, phase_id));
CREATE TABLE IF NOT EXISTS npc_actor(         -- enemy actor ids of a report -> game NPC (bosses included)
  report TEXT, actor_id INT, game_id INT, PRIMARY KEY(report, actor_id));
CREATE INDEX IF NOT EXISTS ix_pc ON player_cast(report, fight_id);
CREATE INDEX IF NOT EXISTS ix_ec ON enemy_cast(report, fight_id);
CREATE INDEX IF NOT EXISTS ix_pb ON player_buff(report, fight_id);
"""


def db_path(cls: str | None = None, spec: str | None = None) -> Path:
    """One corpus per spec (the ranked player of a kill is the analyzed spec's): corpus-<class>-<spec>.sqlite.
    The first corpus (before specs were separated) was the Elemental Shaman's: it is renamed on first use."""
    if cls is None or spec is None:
        from paf import settings

        cls, spec = cls or settings.get("class"), spec or settings.get("spec")
    p = data_dir() / f"corpus-{cls.lower()}-{spec.lower()}.sqlite"
    legacy = data_dir() / "corpus.sqlite"
    if not p.exists() and legacy.exists() and (cls.lower(), spec.lower()) == ("shaman", "elemental"):
        legacy.rename(p)
    return p


MIGRATIONS = [
    ("player_cast", "target_id", "INT"),
    ("player_cast", "target_instance", "INT"),
]


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table, column, kind in MIGRATIONS:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    return con


def clear_fight_rows(con: sqlite3.Connection, report: str, fight_id: int) -> None:
    """Remove derived rows of a kill (before re-fetching it)."""
    for table in ("phase", "add_instance", "player", "damage_by_target", "enemy_cast",
                  "player_cast", "player_buff", "mech_event", "mech_status", "unit_window", "unit_status",
                  "boss_aura", "aura_status"):
        con.execute(f"DELETE FROM {table} WHERE report=? AND fight_id=?", (report, fight_id))
