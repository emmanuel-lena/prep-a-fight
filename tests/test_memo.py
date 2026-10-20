import sqlite3
import time

from paf.corpus.memo import by_corpus


def test_a_page_reads_the_corpus_once_until_it_changes(tmp_path):
    """Issue #30: the boss and raid lead pages computed from the corpus on every visit (1.7 s and 1.3 s)."""
    con = sqlite3.connect(tmp_path / "corpus.sqlite")
    con.execute("CREATE TABLE fight(id INT)")
    con.execute("INSERT INTO fight VALUES (1)")
    con.commit()
    calls = []

    @by_corpus
    def kills(c, boss):
        calls.append(boss)
        return [r[0] for r in c.execute("SELECT id FROM fight")]

    assert kills(con, 7) == [1] and kills(con, 7) == [1] and calls == [7]
    kills(con, 7).append(99)  # a caller changing its copy leaves the cache alone
    assert kills(con, 7) == [1]
    time.sleep(0.01)
    con.execute("INSERT INTO fight VALUES (2)")  # a collect adds kills: computed again
    con.commit()
    assert kills(con, 7) == [1, 2] and calls == [7, 7]


def test_a_database_without_a_file_is_never_cached():
    con = sqlite3.connect(":memory:")
    calls = []

    @by_corpus
    def f(c):
        calls.append(1)
        return 1

    f(con), f(con)
    assert calls == [1, 1]


def test_a_recent_quota_read_answers_a_page(tmp_path, monkeypatch):
    """Settings and the raid queue asked Warcraft Logs on every render; a read under two minutes old is enough."""
    import json

    from paf import wcl

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    f = wcl._quota_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"spent": 120, "limit": 3600, "reset_at": time.time() + 725, "read_at": time.time()}))

    class Refuses:
        def rate_limit(self):
            raise AssertionError("asked Warcraft Logs")

    assert wcl.quota_line(Refuses()) == "120 / 3600 points used this hour (reset in 12 min)"
    left, _ = wcl.quota_left(Refuses())
    assert left == 3480
