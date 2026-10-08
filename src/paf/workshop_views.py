"""The workshop's result pages (paf.results data): a verdict first, in one sentence, then what supports it, with game
icons and gain bars. The text output stays one click away (the log)."""

from __future__ import annotations

import re
from html import escape as e
from pathlib import Path

SLOTS = {"head": "Head", "neck": "Neck", "shoulder": "Shoulders", "back": "Back", "chest": "Chest", "wrist": "Wrists",
         "hands": "Hands", "waist": "Waist", "legs": "Legs", "feet": "Feet", "finger": "Ring", "finger1": "Ring",
         "finger2": "Ring", "trinket": "Trinket", "trinket1": "Trinket", "trinket2": "Trinket",
         "main_hand": "Main hand", "off_hand": "Off hand", "two_hand": "Two-hand", "weapon": "Weapons", "rings": "Rings",
         "trinkets": "Trinkets"}
_RUNS = re.compile(r"^Runs(?: and best set)?:\s*(.+?)\s*$", re.M)


def run_dir(log: str) -> Path | None:
    m = list(_RUNS.finditer(log))
    return Path(m[-1].group(1)) if m else None


def _pct(v: float | None, digits: int = 1) -> str:
    return "&ndash;" if v is None else f"{v:+.{digits}f}%".replace("-", "&minus;")


def _bar(v: float, scale: float) -> str:
    """A gain bar from a centre line: right and green for a gain, left and red for a loss."""
    w = 0 if not scale else min(50.0, abs(v) / scale * 50)
    side = "pos" if v >= 0 else "neg"
    return f"<span class='gbar'><span class='g {side}' style='width:{w:.1f}%'></span></span>"


def _item_icons(rows: list[dict]) -> dict[int, str]:
    from paf.icons import icons_for

    refs = {str(r["item_id"]): f"item={r['item_id']}" for r in rows if r.get("item_id")}
    try:
        return {int(k): v for k, v in icons_for(refs).items()}
    except Exception:  # noqa: BLE001 - offline: no icons
        return {}


def _img(icon: str, cls: str = "it-ic") -> str:
    from paf import icons

    return icons.img(icon, "large", cls) if icon else f"<span class='{cls} none'></span>"


def _verdict(kind: str, title: str, text: str = "", big: str = "") -> str:
    mark = {"go": "&#8593;", "ok": "&#10003;", "warn": "!"}[kind]
    return (f"<div class='verdict {kind}'><span class='v-mark' aria-hidden='true'>{mark}</span><div><b>{title}</b>"
            + (f"<p>{text}</p>" if text else "") + "</div>" + (f"<span class='v-big'>{big}</span>" if big else "")
            + "</div>")


def talents(d: dict) -> str:
    err = d.get("error") or 0.2
    rows = [r for r in d.get("rows", []) if r.get("gain") is not None]
    best = max(rows, key=lambda r: r["gain"], default=None)
    if best and best["gain"] > 2 * err:
        both = set(best["take"]) & set(best["drop"])  # a name on two talent nodes: not a change worth saying
        chips = ("".join(f"<span class='chip add'>+ {e(x)}</span>" for x in best["take"] if x not in both)
                 + "".join(f"<span class='chip drop'>&minus; {e(x)}</span>" for x in best["drop"] if x not in both))
        copy = (f"<button type='button' class='btn go' data-copy='{e(best['code'])}'>Copy the talents</button>"
                if best.get("code") else "")
        head = _verdict("go", f"Switch to <span>{e(best['label'])}</span>",
                        f"Played by {best['players']} top players. What changes:", _pct(best["gain"], 2))
        head += f"<div class='chips'>{chips}</div><div class='v-act'>{copy}</div>"
    else:
        head = _verdict("ok", "Keep your talents", "No build of the top players does better with your character on "
                              "this fight (the differences are within the error).")
    scale = max((abs(r["gain"]) for r in rows), default=1) or 1
    lines = "".join(
        f"<li><span class='l-name'><b>{e(r['label'])}</b><small>{r['players']} top players</small></span>"
        f"{_bar(r['gain'], scale)}<span class='l-val {'pos' if r['gain'] > 2 * err else 'neg' if r['gain'] < -2 * err else ''}'>"
        f"{_pct(r['gain'], 2)}</span></li>" for r in sorted(rows, key=lambda r: -r["gain"]))
    return (f"{head}<h3>Every build, on your character</h3><ul class='glist'>{lines}</ul>"
            f"<p class='ws-fine'>Compared with your current build, on {e(d.get('boss', 'the boss'))}. Differences under "
            f"&plusmn;{2 * err:.2f}% are noise.</p>")


def loot(d: dict) -> str:
    err = d.get("error") or 0.2
    rows = d.get("rows", [])
    icons = _item_icons(rows)
    good = [r for r in rows if r["gain"] > 2 * err]
    bad = [r for r in rows if r["gain"] <= 2 * err]
    where = ", ".join(d.get("bosses", [])[:3]) + ("&hellip;" if len(d.get("bosses", [])) > 3 else "")
    if good:
        head = _verdict("go", "1 item worth it for you" if len(good) == 1 else f"{len(good)} items worth it for you",
                        f"From {e(where)}, at item level {d.get('ilvl')}.", _pct(good[0]["gain"]))
    else:
        head = _verdict("ok", "Nothing here is an upgrade for you", f"From {e(where)}, at item level {d.get('ilvl')}: "
                              "what you wear is already as good or better.")
    def card(r: dict, scale: float) -> str:
        return (f"<li class='icard'>{_img(icons.get(r['item_id'], ''))}<span class='l-name'><b>{e(r['name'])}</b>"
                f"<small><span>{e(SLOTS.get(r['slot'], r['slot']))}</span> &middot; {e(r['boss'])}</small></span>"
                f"{_bar(r['gain'], scale)}<span class='l-val {'pos' if r['gain'] > 2 * err else 'neg'}'>"
                f"{_pct(r['gain'])}</span></li>")
    def scale(lst: list[dict]) -> float:  # each list its own scale: a small gain is not lost next to big losses
        return max((abs(r["gain"]) for r in lst), default=1) or 1

    body = f"<ul class='glist items'>{''.join(card(r, scale(good)) for r in good)}</ul>" if good else ""
    if bad:
        body += (f"<details class='more'><summary>Not upgrades ({len(bad)})</summary><ul class='glist items'>"
                 f"{''.join(card(r, scale(bad)) for r in bad)}</ul></details>")
    evs = [x for x in d.get("ev", []) if x["ev"] > 0]
    ev = ("<h3>Which boss is worth it</h3><ul class='glist'>" + "".join(
        f"<li><span class='l-name'><b>{e(x['boss'])}</b><small>{x['n']} items for you</small></span>"
        f"{_bar(x['ev'], max(y['ev'] for y in evs))}<span class='l-val pos'>{_pct(x['ev'], 2)}</span></li>"
        for x in evs) + "</ul>") if len(evs) > 1 else ""
    return (f"{head}{body}{ev}<p class='ws-fine'>Each item simmed in its slot on your character; differences under "
            f"&plusmn;{2 * err:.2f}% are noise.</p>")


def topgear(d: dict) -> str:
    err = d.get("error") or 0.2
    rows = d.get("rows", [])
    if not rows:
        return _verdict("warn", "Nothing to compare", "No item in your bags could replace what you wear: paste a "
                                "/simc export with your bags.")
    best = rows[0]
    icons = _item_icons([i for r in rows[:4] for c in r["changes"] for i in c["items"]])

    def item(slot: str, i: dict) -> str:
        meta = [SLOTS.get(slot, slot)] + ([str(i["ilvl"])] if i.get("ilvl") else [])
        meta += [i["source"]] if i.get("source") not in ("bags", "equipped", None) else []
        return (f"<li class='icard'>{_img(icons.get(i.get('item_id') or 0, ''))}<span class='l-name'>"
                f"<b>{e(i['name'] or '?')}</b><small>{' &middot; '.join(f'<span>{e(m)}</span>' for m in meta)}</small>"
                f"</span></li>")

    def changes(r: dict) -> str:
        return "".join(item(c["slot"], i) for c in r["changes"] for i in c["items"])
    if best["gain"] > 2 * err:
        head = _verdict("go", "Put on these items", f"The best set from your bags{' on ' + e(', '.join(d.get('fights', []))) if d.get('fights') else ''}.",
                        _pct(best["gain"], 2)) + f"<ul class='glist items'>{changes(best)}</ul>"
    else:
        head = _verdict("ok", "Keep what you wear", "No combination of your bags does better (the differences are "
                              "within the error).")
    others = rows[1:6] if best["gain"] > 2 * err else rows[:5]
    more = "".join(f"<details class='more'><summary><b>{_pct(r['gain'], 2)}</b> &middot; "
                   f"{e(', '.join(i['name'] or '?' for c in r['changes'] for i in c['items']))}</summary>"
                   f"<ul class='glist items'>{changes(r)}</ul></details>" for r in others if r["changes"])
    title = "Other good sets" if best["gain"] > 2 * err else "The closest sets (within the error)"
    return (f"{head}" + (f"<h3>{title}</h3>{more}" if more else "")
            + f"<p class='ws-fine'>Differences under &plusmn;{2 * err:.2f}% are noise.</p>")


def cooldowns(d: dict) -> str:
    labels = {"boss": "For boss damage", "total": "For total damage (pad)", "adds": "On the adds",
              "secondary": "On the secondary targets"}
    out = ""
    for p in d.get("plans", []):
        worth = p["gain"] > 2 * (p.get("error") or 0.2)
        rules = "".join(f"<li><b>{e(r['cd'])}</b><span>{e(r['how'])}</span></li>" for r in p["rules"])
        body = (f"<ul class='rules'>{rules}</ul>" if worth and rules else
                "<p>Press your cooldowns as soon as they are ready: holding them gains nothing here.</p>")
        flags = "".join(f"<p class='ws-fine'>! {e(f)}</p>" for f in p.get("flags", []))
        out += (f"<div class='plan {'go' if worth else 'ok'}'><div class='p-head'><b>{e(labels.get(p['objective'], p['objective']))}</b>"
                f"<span class='v-big'>{_pct(p['gain'], 2) if worth else '&#10003;'}</span></div>{body}{flags}</div>")
    return out or _verdict("warn", "No plan", "The optimization found nothing to compare.")


VIEWS = {"talents": talents, "loot": loot, "topgear": topgear, "cooldowns": cooldowns}


def render(data: dict) -> str | None:
    view = VIEWS.get(data.get("kind", ""))
    return view(data) if view else None


CSS = """<style>
.verdict{display:flex;gap:16px;align-items:center;padding:18px 20px;border-radius:16px;margin:0 0 14px;
  border:1px solid var(--line);background:var(--surface)}
.verdict.go{border-color:color-mix(in srgb,var(--pos) 55%,var(--line));background:color-mix(in srgb,var(--pos) 9%,var(--surface))}
.verdict.ok{border-color:color-mix(in srgb,var(--accent) 45%,var(--line))}
.verdict.warn{border-color:color-mix(in srgb,var(--warn) 55%,var(--line))}
.v-mark{flex:none;width:44px;height:44px;border-radius:50%;display:grid;place-items:center;font-size:22px;font-weight:700;color:#fff}
.go .v-mark{background:var(--pos)} .ok .v-mark{background:var(--accent)} .warn .v-mark{background:var(--warn)}
.verdict>div{flex:1;min-width:0} .verdict b{font:600 22px/1.25 'Fraunces',Georgia,serif;display:block}
.verdict b span{color:var(--pos)} .verdict p{margin:4px 0 0;color:var(--muted);font-size:15px}
.v-big{font:700 30px/1 var(--font-data);color:var(--pos);white-space:nowrap}
.ok .v-big{color:var(--accent)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.chip{padding:4px 10px;border-radius:999px;font-size:14px;font-weight:600;border:1px solid var(--line)}
.chip.add{color:var(--pos);border-color:color-mix(in srgb,var(--pos) 45%,transparent)}
.chip.drop{color:var(--neg);border-color:color-mix(in srgb,var(--neg) 40%,transparent)}
.v-act{margin:0 0 6px}
.ws-answer h3{font:600 17px 'Fraunces',Georgia,serif;margin:22px 0 10px;text-transform:none;letter-spacing:0;color:var(--fg)}
.glist{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.glist li{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(80px,1fr) 78px;gap:14px;align-items:center;
  padding:9px 10px;border-radius:10px} .glist li:hover{background:var(--surface-2)}
.glist.items li{grid-template-columns:44px minmax(0,1.3fr) minmax(80px,1fr) 78px}
.glist.items li:not(:has(.gbar)){grid-template-columns:44px minmax(0,1fr)}
.l-name{display:flex;flex-direction:column;gap:2px;min-width:0} .l-name b{font-size:15.5px;overflow:hidden;text-overflow:ellipsis}
.l-name small{color:var(--muted);font-size:13px}
.l-val{font:600 15px var(--font-data);text-align:right;font-variant-numeric:tabular-nums}
.l-val.pos{color:var(--pos)} .l-val.neg{color:var(--neg)}
.gbar{position:relative;height:8px;border-radius:4px;background:var(--surface-2)}
.gbar::before{content:"";position:absolute;left:50%;top:-3px;bottom:-3px;border-left:1.5px solid var(--line)}
.gbar .g{position:absolute;top:0;bottom:0;border-radius:4px}
.gbar .pos{left:50%;background:var(--pos)} .gbar .neg{right:50%;background:var(--neg);opacity:.75}
.it-ic{width:40px;height:40px;border-radius:8px;margin:0;box-shadow:0 1px 4px rgba(0,0,0,.25)}
.it-ic.none{display:inline-block;background:var(--surface-2);border:1px solid var(--line)}
details.more{margin:6px 0} details.more>summary{cursor:pointer;color:var(--muted);padding:6px 4px}
.plan{padding:16px 18px;border-radius:14px;border:1px solid var(--line);margin:0 0 12px;background:var(--surface)}
.plan.go{border-color:color-mix(in srgb,var(--pos) 50%,var(--line))}
.p-head{display:flex;justify-content:space-between;align-items:center;gap:12px}
.p-head b{font:600 19px 'Fraunces',Georgia,serif} .p-head .v-big{font-size:22px}
.rules{list-style:none;padding:0;margin:10px 0 0;display:grid;gap:8px}
.rules li{display:flex;gap:10px;flex-wrap:wrap} .rules li b{min-width:150px} .rules li span{color:var(--muted)}
@media (max-width:640px){.glist li{grid-template-columns:minmax(0,1fr) 70px}.glist li .gbar{display:none}
  .glist.items li{grid-template-columns:40px minmax(0,1fr) 70px}.verdict{flex-wrap:wrap}}
</style>"""
