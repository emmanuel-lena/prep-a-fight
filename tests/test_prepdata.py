import dataclasses
import pickle
import sqlite3

from paf.prep_report import PrepData, render, sheet_pickle


@dataclasses.dataclass
class Sheet:
    rows: list
    rule: object
    name: str = "x"


def test_the_sheet_pickles_with_rows_and_lambdas():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT 1 AS a, 'b' AS b").fetchone()
    back = pickle.loads(sheet_pickle(Sheet([row], lambda x: x)))
    assert back.rows == [{"a": 1, "b": "b"}] and back.rule is None and back.name == "x"


def test_a_fresh_prep_with_database_rows_renders():
    """A fresh prep holds sqlite3 rows (a pickle read back does not): render copied them with deepcopy and every
    new prep failed at its last step."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    d = PrepData("Boss", "heroic", "Elemental", "X", duration=300)
    d.mechanics = [con.execute("SELECT 1 AS a").fetchone()]
    assert "<html" in render(d).lower()
