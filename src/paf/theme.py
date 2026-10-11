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
        'family=Chakra+Petch:wght@500;600;700&family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;1,9..144,400'
        '&family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@400;500;600'
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


def _svg(path: str) -> str:
    return (f"<svg viewBox='0 0 24 24' width='20' height='20' aria-hidden='true'><path d='{path}' fill='none' "
            f"stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/></svg>")


# the app's places, each with a drawn icon (one stroke, one weight)
PLACES = (
    ("/", "Home", "M3 11.5 12 4l9 7.5M6 10v9.5h4.5V15h3v4.5H18V10"),
    ("/tools", "Tools", "M14.5 6.5a4 4 0 0 0-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 0 0 5.3-5.3l-2.6 2.6-2.4-.6-.6-2.4z"),
    ("/raidlead", "Raid lead", "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 20a5.5 5.5 0 0 1 11 0M16 11a3 3 0 1 0 0-6"
                               "M18 20a5.5 5.5 0 0 0-3-4.9"),
    ("/characters", "Characters", "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20.5a7.5 7.5 0 0 1 15 0"),
    ("/settings", "Settings", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 13.5l1.6 1.2-2 3.4-1.9-.7a7 7 0 0 1-2 1.2L14.8"
                              " 21h-4l-.3-2a7 7 0 0 1-2-1.2l-1.9.7-2-3.4 1.6-1.2a7 7 0 0 1 0-2.4L4.6 9.3l2-3.4 1.9.7a7 7"
                              " 0 0 1 2-1.2L10.8 3h4l.3 2a7 7 0 0 1 2 1.2l1.9-.7 2 3.4-1.6 1.2a7 7 0 0 1 0 2.4z"),
    ("/feedback", "Feedback", "M4 5h16v11H9l-5 4z"),
)
BACK_ICON = ("<button type='button' class='side-back' hidden aria-label='Go back' title='Go back' "
             "onclick='history.back()'>" + _svg("M15 5l-7 7 7 7") + "<span>Back</span></button>"
             "<script>(function(){var b=document.currentScript.previousElementSibling;"
             "if(history.length>1&&location.pathname!=='/')b.hidden=false;})();</script>")
# the place the page belongs to, lit in the side bar
SIDE_JS = ("<script>(function(){var p=location.pathname,best=null;document.querySelectorAll('.side-nav a').forEach("
           "function(a){var h=a.getAttribute('href');if(p===h||(h!=='/'&&p.indexOf(h)===0)){best=a}});"
           "if(!best&&(p.indexOf('/view/')===0||p.indexOf('/boss')===0||p.indexOf('/job/')===0))"
           "best=document.querySelector(\".side-nav a[href='/']\");if(best){best.classList.add('on');"
           "best.setAttribute('aria-current','page')}})();</script>")


def sidebar(extra: str = "", who: str = "", foot: str = "") -> str:
    """The app's side bar (DESIGN.md): the brand (home), Back (the desktop window has no browser buttons), the app's
    places, `extra` (what this page adds: a sheet's boss and links), and at the bottom `foot` and the character
    menu `who`. A rail of icons on a narrow window, a bar at the bottom on a phone."""
    links = "".join(f"<a href='{h}' title='{label}'>{_svg(d)}<span>{label}</span></a>" for h, label, d in PLACES)
    return (f"<aside class='side'><div class='side-top'><a class='brand' href='/'>prep-a-<b>fight</b></a>"
            f"{BACK_ICON}</div><nav class='side-nav' aria-label='The app'>{links}</nav>"
            + (f"<div class='side-extra'>{extra}</div>" if extra else "")
            + f"<div class='side-foot'>{foot}{who}</div></aside>{SIDE_JS}")


# the game's class colors: the app takes the active character's (accent, its soft background, the header's stripe)
CLASS_COLORS = {"deathknight": "#C41E3A", "demonhunter": "#A330C9", "druid": "#FF7C0A", "evoker": "#33937F",
                "hunter": "#AAD372", "mage": "#3FC7EB", "monk": "#00FF98", "paladin": "#F48CBA", "priest": "#FFFFFF",
                "rogue": "#FFF468", "shaman": "#0070DD", "warlock": "#8788EE", "warrior": "#C69B6D"}


def _luminance(rgb: tuple[float, ...]) -> float:
    def ch(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(ch, rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def _keep(color: str, toward: str, ground: str, cap: float, target: float = 4.6) -> int:
    """The share of the class color (in %, at most `cap`) mixed with `toward` that still reads as text on `ground`
    (WCAG contrast `target`): a bright class (priest, rogue, monk) is darkened more than a deep one."""
    c, t, g = _rgb(color), _rgb(toward), _luminance(_rgb(ground))
    for keep in range(round(cap * 100), -1, -1):
        mixed = _luminance(tuple(a * keep / 100 + b * (1 - keep / 100) for a, b in zip(c, t, strict=True)))
        hi, lo = max(mixed, g), min(mixed, g)
        if (hi + 0.05) / (lo + 0.05) >= target:
            return keep
    return 0


def class_accent(class_name: str) -> str:
    """A <style> giving the app the color of the class: darkened on the light theme, lightened a little on the dark
    one, each as much as needed for text in the accent to pass WCAG AA on the pages' darkest (lightest) surface.
    '' for an unknown class."""
    color = CLASS_COLORS.get((class_name or "").lower().replace(" ", ""))
    if not color:
        return ""
    light = _keep(color, "#000000", "#f1eaf0", 0.68)  # --surface-2 of the light theme
    dark_keep = _keep(color, "#ffffff", "#2b212c", 0.70)  # --surface-2 of the dark theme
    dark = (f"--accent:color-mix(in srgb,var(--class) {dark_keep}%,#fff);"
            "--accent-soft:color-mix(in srgb,var(--class) 22%,#181219)")
    return (f"<style>:root{{--class:{color};--accent:color-mix(in srgb,var(--class) {light}%,#000);"
            "--accent-soft:color-mix(in srgb,var(--class) 16%,#fff);"
            "--stripe:linear-gradient(90deg,var(--class),color-mix(in srgb,var(--class) 55%,#000))}"
            f"@media (prefers-color-scheme:dark){{:root:not([data-theme=\"light\"]){{{dark}}}}}"
            f":root[data-theme=\"dark\"]{{{dark}}}</style>")


DIFFICULTY_NAMES = {"lfr": "LFR", "normal": "Normal", "heroic": "Heroic", "mythic": "Mythic"}


def diff_pill(difficulty: str | None) -> str:
    """A difficulty's pill: its word and its rarity shape (a green triangle, a blue square, a purple pentagon), never
    the gold of a selection. Takes the key ("heroic") or the label ("Heroic")."""
    import html

    key = (difficulty or "").strip().lower()
    word = DIFFICULTY_NAMES.get(key, difficulty or "?")
    shape = f" {key}" if key in ("normal", "heroic", "mythic") else ""
    return f'<span class="pill diff{shape}">{html.escape(word)}</span>'
