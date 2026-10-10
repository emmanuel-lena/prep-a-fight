import dataclasses
import pickle
import sqlite3

from paf.cli import _pickle_sheet


@dataclasses.dataclass
class Sheet:
    rows: list
    rule: object
    name: str = "x"


def test_the_sheet_pickles_with_rows_and_lambdas():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT 1 AS a, 'b' AS b").fetchone()
    back = pickle.loads(_pickle_sheet(Sheet([row], lambda x: x)))
    assert back.rows == [{"a": 1, "b": "b"}] and back.rule is None and back.name == "x"
