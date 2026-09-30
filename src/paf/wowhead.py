"""Wowhead links and tooltips for spells and items in the HTML pages (like Warcraft Logs does).

The tooltips come from Wowhead's public script; without network the links still work as plain links.
"""

from __future__ import annotations

import html
import re

SCRIPT = ('<script>const whTooltips={colorLinks:true,iconizeLinks:true,renameLinks:false};</script>'
          '<script src="https://wow.zamimg.com/js/tooltips.js" async></script>')


def spell_ref(spell_id: int) -> str:
    return f"spell={spell_id}"


def item_ref(item_id: int, ilvl: int | None = None, bonus: str | None = None) -> str:
    ref = f"item={item_id}"
    if ilvl:
        ref += f"&ilvl={ilvl}"
    if bonus:
        ref += "&bonus=" + bonus.replace("/", ":")
    return ref


def link(text: str, ref: str | None) -> str:
    """Escaped text, as a Wowhead link when a reference is known."""
    t = html.escape(text)
    if not ref:
        return t
    kind, _, rest = ref.partition("=")
    path = f"{kind}={rest.split('&', 1)[0]}"
    return (f'<a class="wh" href="https://www.wowhead.com/{path}" data-wowhead="{html.escape(ref)}" '
            f'target="_blank" rel="noopener">{t}</a>')


def linkify(text: str, refs: dict[str, str]) -> str:
    """Escape the text and turn every known name in it into a Wowhead link (longest names first)."""
    names = sorted((n for n in refs if n), key=len, reverse=True)
    if not names:
        return html.escape(text)
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(n) for n in names) + r")(?!\w)")
    out, pos = [], 0
    for m in pattern.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        out.append(link(m.group(0), refs[m.group(0)]))
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def profile_refs(profile) -> dict[str, str]:
    """Item name -> Wowhead reference (with its bonus ids and item level) for a parsed /simc export."""
    refs: dict[str, str] = {}
    for it in [*profile.equipped.values(), *profile.candidates]:
        if it.name and it.item_id and it.name not in refs:
            refs[it.name] = item_ref(it.item_id, it.ilvl, it.fields.get("bonus_id"))
    return refs
