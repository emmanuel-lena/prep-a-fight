"""Results computed from a corpus, kept in memory while its file is unchanged (issue #30: the boss and raid lead
pages read the corpus again on every visit, 1-2 s each). Keyed by the database file's and its WAL's size and time:
a collect that adds kills changes them, and the next visit computes again. Callers get a copy, never the cached one.
"""

from __future__ import annotations

import copy
import functools
import os
import sqlite3

LIMIT = 256  # results kept; past it the memo starts over (a few bosses, a few specs: far below)
_memo: dict = {}


def _stamp(con: sqlite3.Connection) -> tuple | None:
    """The corpus file as it is now, or None for a database without a file (tests): never cached."""
    path = next((r[2] for r in con.execute("PRAGMA database_list") if r[1] == "main"), "")
    if not path:
        return None
    out: list = [path]
    for p in (path, path + "-wal"):
        try:
            st = os.stat(p)
            out += [st.st_mtime_ns, st.st_size]
        except OSError:
            out += [0, 0]
    return tuple(out)


def by_corpus(fn):
    """Cache fn(con, *args) (hashable args) while the corpus file of `con` is unchanged."""
    @functools.wraps(fn)
    def wrapper(con: sqlite3.Connection, *args):
        stamp = _stamp(con)
        if stamp is None:
            return fn(con, *args)
        key = (fn.__module__, fn.__qualname__, stamp, args)
        if key not in _memo:
            if len(_memo) >= LIMIT:
                _memo.clear()
            _memo[key] = fn(con, *args)
        return copy.deepcopy(_memo[key])
    return wrapper
