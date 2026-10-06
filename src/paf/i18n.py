"""The app in the player's language (issue #2).

Pages are written in English and translated when they are sent: a catalog of phrases per language
(``paf/locale/<code>.py``: ``NAME``, ``PHRASES`` exact texts, ``PATTERNS`` regular expressions for the sentences that
carry numbers). Adding a language = adding its catalog; the setting lists the catalogs present. Scripts, styles,
code blocks and tag attributes other than a few visible ones are left alone; a phrase missing from a catalog stays
in English. Game names (spells, items, bosses) come from the game's own data in that language (WOW_LOCALES), not
from the catalogs.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from paf import settings

# the languages World of Warcraft is played in: our code -> the game's locale (Wowhead, Encounter Journal)
WOW_LOCALES = {"en": "enUS", "fr": "frFR", "de": "deDE", "es": "esES", "it": "itIT", "pt": "ptBR", "ru": "ruRU",
               "ko": "koKR", "zh": "zhCN"}
# Windows primary language ids (LANGID & 0x3FF) -> our code
_WINDOWS = {0x09: "en", 0x0C: "fr", 0x07: "de", 0x0A: "es", 0x10: "it", 0x16: "pt", 0x19: "ru", 0x12: "ko",
            0x04: "zh"}


def available() -> dict[str, str]:
    """code -> name of the languages the app has a catalog for (English always)."""
    out = {"en": "English"}
    for f in sorted((Path(__file__).parent / "locale").glob("*.py")):
        if f.stem != "__init__":
            out[f.stem] = _module(f.stem).NAME
    return out


def system_language() -> str:
    """The language of Windows (or of the system locale elsewhere), as one of our codes."""
    try:
        import ctypes

        code = _WINDOWS.get(ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF, "en")
    except (AttributeError, OSError):
        import locale

        code = (locale.getlocale()[0] or "en")[:2].lower()
    return code if code in WOW_LOCALES else "en"


def language() -> str:
    """The language of the pages: PAF_LANG, the setting, else Windows' language when the app has it, else English."""
    import os

    chosen = os.environ.get("PAF_LANG") or settings.get("language")
    langs = available()
    if chosen in langs:
        return chosen
    sys_lang = system_language()
    return sys_lang if sys_lang in langs else "en"


def wow_locale(lang: str | None = None) -> str:
    return WOW_LOCALES.get(lang or language(), "enUS")


def _module(code: str):
    from importlib import import_module

    return import_module(f"paf.locale.{code}")


@dataclass
class Catalog:
    words: dict[str, str]  # one-word texts, translated only when they are a whole text of the page
    phrases: dict[str, str]  # longer texts, translated wherever they appear (on word boundaries)
    phrase_rx: re.Pattern | None
    patterns: list[tuple[re.Pattern, str]]


def _compile(pairs: dict[str, str], patterns: list[tuple[str, str]]) -> Catalog:
    """Ready to match: each text also in its HTML-escaped form (' as &#x27;, & as &amp;)."""
    words, phrases = {}, {}
    for en, tr in pairs.items():
        for a, b in ((en, tr), (html.escape(en), html.escape(tr))):  # the escaped form last: it wins, safe anywhere
            (words if " " not in a.strip() else phrases)[a] = b
    keys = sorted(phrases, key=len, reverse=True)
    rx = re.compile(r"(?<![\w])(" + "|".join(re.escape(k) for k in keys) + r")(?![\w])") if keys else None
    pats = []
    for pat, tr in patterns:
        pats.append((re.compile(pat), tr))
        esc = pat.replace("'", "&#x27;")
        if esc != pat:
            pats.append((re.compile(esc), tr.replace("'", "&#x27;")))
    return Catalog(words, phrases, rx, pats)


@cache
def catalog(lang: str) -> Catalog:
    """A language's catalog of the app's own texts."""
    if lang == "en":
        return Catalog({}, {}, None, [])
    mod = _module(lang)
    return _compile(mod.PHRASES, mod.PATTERNS)


_NAMES: dict[str, tuple[float, Catalog]] = {}


def game_names(lang: str) -> Catalog:
    """The game's names and journal texts in `lang` (paf.names), reloaded when its table changes."""
    from paf import names

    locale = WOW_LOCALES.get(lang, "enUS")
    path = names._path(locale)
    mtime = path.stat().st_mtime if path.is_file() else 0.0
    if lang == "en" or not mtime:
        return Catalog({}, {}, None, [])
    if _NAMES.get(locale, (None,))[0] != mtime:
        _NAMES[locale] = (mtime, _compile(names.mapping(locale), []))
    return _NAMES[locale][1]


_SKIP = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<pre\b.*?</pre>|<textarea\b.*?</textarea>|<[^>]+>)",
                   re.S | re.I)
_VISIBLE_ATTR = re.compile(r'((?:placeholder|title|aria-label|alt|data-title|data-text)=)(["\'])(.*?)\2')
_RAW = ("<script", "<style", "<pre", "<textarea")


def _apply(s: str, cat: Catalog) -> str:
    core = s.strip()
    if core in cat.words:
        return s.replace(core, cat.words[core])
    if cat.phrase_rx is not None:
        s = cat.phrase_rx.sub(lambda m: cat.phrases[m.group(1)], s)
    for rx, tr in cat.patterns:
        s = rx.sub(tr, s)
    return s


def _text(s: str, lang: str) -> str:
    if not s.strip():
        return s
    if "\n" in s:  # a sentence written over several lines of HTML: one line, so that the catalog finds it
        s = re.sub(r"\s+", " ", s)
    return _apply(_apply(s, game_names(lang)), catalog(lang))  # game names first: sentences carry them


def translate(html: str, lang: str | None = None) -> str:
    """The page in `lang` (default: the player's language)."""
    lang = lang or language()
    if lang == "en":
        return html
    out = []
    for i, part in enumerate(_SKIP.split(html)):
        if i % 2 == 0:  # text between tags
            out.append(_text(part, lang))
        elif not part.lower().startswith(_RAW):  # a tag: only its visible attributes
            out.append(_VISIBLE_ATTR.sub(lambda m: m.group(1) + m.group(2) + _text(m.group(3), lang) + m.group(2),
                                         part))
        else:
            out.append(part)
    return "".join(out)


def untranslated(html: str, lang: str) -> list[str]:
    """The visible texts of a page that the catalog of `lang` leaves in English (to write a catalog)."""
    out = []
    for i, part in enumerate(_SKIP.split(html)):
        texts = [part] if i % 2 == 0 else ([m.group(3) for m in _VISIBLE_ATTR.finditer(part)]
                                            if not part.lower().startswith(_RAW) else [])
        for s in texts:
            s = " ".join(s.split())
            if re.search(r"[A-Za-z]{3,}", s) and _text(s, lang) == s:
                out.append(s)
    return out
