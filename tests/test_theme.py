import re
from pathlib import Path

from paf import theme

SRC = Path(__file__).resolve().parents[1] / "src" / "paf"


def test_every_stylesheet_named_in_the_code_exists():
    names = set()
    for p in SRC.rglob("*.py"):
        names |= set(re.findall(r'\bstyle\("([\w-]+)"\)', p.read_text(encoding="utf-8")))
    assert {"tokens", "base", "polish", "web", "prep"} <= names
    for name in names:
        assert theme.style(name).strip(), name


def test_the_stylesheets_are_plain_css():
    for p in (SRC / "styles").glob("*.css"):
        text = p.read_text(encoding="utf-8")
        assert "<style" not in text and "</style" not in text, p.name
        assert text.count("{") == text.count("}"), p.name


def test_no_module_carries_a_style_block():
    """DESIGN.md: every page's CSS lives in src/paf/styles/, none in the modules."""
    for p in SRC.rglob("*.py"):
        if p.name == "loading.py":  # its startup page is a whole document shown before the server runs
            continue
        assert not re.search(r"^\w*CSS\s*=\s*(\"\"\"|''')", p.read_text(encoding="utf-8"), re.M), p.name
