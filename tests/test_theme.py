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


def test_every_class_accent_reads_as_text_on_both_themes():
    def contrast(a, b):
        hi, lo = sorted((theme._luminance(a), theme._luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    for cls, color in theme.CLASS_COLORS.items():
        css = theme.class_accent(cls)
        light, dark = (int(x) for x in re.findall(r"--accent:color-mix\(in srgb,var\(--class\) (\d+)%", css)[::2])
        c = theme._rgb(color)
        on_light = tuple(x * light / 100 for x in c)
        on_dark = tuple(x * dark / 100 + 255 * (1 - dark / 100) for x in c)
        assert contrast(on_light, theme._rgb("#f1eaf0")) >= 4.5, cls  # the rogue's yellow was 2.1:1
        assert contrast(on_dark, theme._rgb("#2b212c")) >= 4.5, cls
