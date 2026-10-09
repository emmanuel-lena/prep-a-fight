"""The visual identity shared by every page (web app, prep sheet, timelines): one palette, light and dark.

Palette: vintage grape #5c415d, vintage grape 2 #694966, dusty lavender #74526c, golden sand #dbd053,
golden bronze #c89933. Grapes carry the structure (header, primary buttons in light mode), the golds the
accents (highlights, primary buttons in dark mode, key numbers). Gold is never used for body text on a light
background (too little contrast).
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files


@cache
def style(name: str) -> str:
    """A stylesheet of src/paf/styles/: every page's CSS lives there, none in the modules (DESIGN.md)."""
    return files("paf").joinpath("styles", f"{name}.css").read_text(encoding="utf-8")


TOKENS = style("tokens")

BASE = style("base")

POLISH = style("polish")

CSS = TOKENS + BASE + POLISH

# Google Fonts (the faces fall back to system ones offline)
HEAD = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" '
        'href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@400;500;600'
        '&display=swap">')


BACK = ("<button type='button' class='nav-back' hidden aria-label='Go back' title='Go back' onclick='history.back()'>"
        "&larr; <span>Go back</span></button><script>(function(){var b=document.currentScript.previousElementSibling;"
        "if(history.length>1&&location.pathname!=='/')b.hidden=false;})();</script>")
# a Home button with a little house, back to the home page from anywhere (hidden on the home page itself)
HOME = ("<a class='nav-back nav-home' href='/' hidden aria-label='Home' title='Home'><svg viewBox='0 0 24 24' "
        "width='16' height='16' aria-hidden='true'><path d='M3 11.5 12 4l9 7.5M6 10v9.5h4.5V15h3v4.5H18V10' "
        "fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>"
        "<span>Home</span></a><script>(function(){var b=document.currentScript.previousElementSibling;"
        "if(location.pathname!=='/')b.hidden=false;})();</script>")


def topbar(right: str = "", home: str = "/", back: bool = False, who: str = "") -> str:
    """The gradient header with the brand; `right` holds navigation or selectors. back: a Back button (the desktop
    window has no browser buttons), shown when there is a page to go back to; who: the active character's menu."""
    return (f'<header class="topbar"><div class="in">{BACK + HOME if back else ""}<a class="brand" href="{home}">'
            f'prep-a-<b>fight</b></a>{who}<div class="nav">{right}</div></div></header>')


# the game's class colors: the app takes the active character's (accent, its soft background, the header's stripe)
CLASS_COLORS = {"deathknight": "#C41E3A", "demonhunter": "#A330C9", "druid": "#FF7C0A", "evoker": "#33937F",
                "hunter": "#AAD372", "mage": "#3FC7EB", "monk": "#00FF98", "paladin": "#F48CBA", "priest": "#FFFFFF",
                "rogue": "#FFF468", "shaman": "#0070DD", "warlock": "#8788EE", "warrior": "#C69B6D"}


def class_accent(class_name: str) -> str:
    """A <style> giving the app the color of the class: darkened on the light theme, lightened a little on the dark
    one, so every class reads on both. '' for an unknown class."""
    color = CLASS_COLORS.get((class_name or "").lower().replace(" ", ""))
    if not color:
        return ""
    dark = ("--accent:color-mix(in srgb,var(--class) 82%,#fff);"
            "--accent-soft:color-mix(in srgb,var(--class) 22%,#181219)")
    return (f"<style>:root{{--class:{color};--accent:color-mix(in srgb,var(--class) 68%,#000);"
            "--accent-soft:color-mix(in srgb,var(--class) 16%,#fff);"
            "--stripe:linear-gradient(90deg,var(--class),color-mix(in srgb,var(--class) 55%,#000))}"
            f"@media (prefers-color-scheme:dark){{:root:not([data-theme=\"light\"]){{{dark}}}}}"
            f":root[data-theme=\"dark\"]{{{dark}}}</style>")
