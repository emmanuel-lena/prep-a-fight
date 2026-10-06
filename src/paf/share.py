"""Share a prep sheet with the raid: publish it through the relay (tools/feedback-worker) and get a link that opens
in any browser, without the app. The sheet goes as the player sees it (translated), made standalone (links to
local files removed). It carries the character's name and gear, so sharing is the player's explicit choice, sheet
by sheet; it expires after 30 days or when the player stops sharing it (the relay's token, kept here).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from paf import __version__
from paf.config import data_dir

REPO = "https://github.com/emmanuel-lena/prep-a-fight"


def _store() -> Path:
    return data_dir() / "web" / "shares.json"


def shares() -> dict[str, dict]:
    p = _store()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        return {}


def _save(data: dict) -> None:
    p = _store()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def standalone(html: str) -> str:
    """The sheet as a page of its own: no links to the app's local files, a line saying where it comes from."""
    html = re.sub(r'<a [^>]*href="(?!https?:|#)[^"]*"[^>]*>(.*?)</a>', r"\1", html, flags=re.S)
    note = (f'<p style="text-align:center;font-size:12px;opacity:.7;margin:24px 0">Prepared with '
            f'<a href="{REPO}" target="_blank" rel="noopener">prep-a-fight</a>, free and open source.</p>')
    return html.replace("</body>", note + "</body>") if "</body>" in html else html + note


def _relay() -> str:
    from paf.pack import relay

    return relay()


def _request(url: str, data: bytes | None = None, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": f"prep-a-fight/{__version__}", **(headers or {})})
    return urllib.request.urlopen(req, timeout=30)


def publish(key: str) -> dict:
    """Publish the prep sheet `key` (report name without 'prep-'); returns {url, id, token, days, ...}."""
    from paf.i18n import translate

    base = _relay()
    if not base:
        raise RuntimeError("sharing needs the relay of an installed copy")
    sheet = data_dir() / "reports" / f"prep-{key}.html"
    html = translate(standalone(sheet.read_text(encoding="utf-8")))
    with _request(f"{base}/s", html.encode("utf-8"), "POST", {"Content-Type": "text/html; charset=utf-8"}) as r:
        info = json.loads(r.read())
    import time

    info["at"] = time.time()
    data = shares()
    data[key] = info
    _save(data)
    return info


def stop(key: str) -> None:
    data = shares()
    info = data.pop(key, None)
    if info:
        try:
            _request(f"{_relay()}/s/{info['id']}", method="DELETE", headers={"X-Share-Token": info["token"]}).close()
        except urllib.error.HTTPError as ex:
            if ex.code not in (403, 404):  # already gone (expired): forget it anyway
                raise
    _save(data)


def current(key: str) -> dict | None:
    """The live share of a sheet, if any (expired ones are forgotten)."""
    import time

    info = shares().get(key)
    if info and time.time() - info.get("at", 0) > info.get("days", 30) * 86400:
        data = shares()
        data.pop(key, None)
        _save(data)
        return None
    return info
