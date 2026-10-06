"""List the texts of the app's pages that a language's catalog does not translate yet.

    .venv/Scripts/python tools/i18n_missing.py fr

Renders the main pages with the data of this computer (home, settings, tools, feedback, a running and a failed
prep, the update banner) and the prep sheets, timelines and raid plans in the reports folder.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter

from paf import i18n, update, web, webtools
from paf.config import data_dir


def pages() -> dict[str, str]:
    out = {"home": web.home().decode(), "settings": web.page("Settings", webtools.settings_page()).decode(),
           "tools": web.page("Tools", webtools.tools_page()).decode(), "feedback": web.page("F", web.feedback_page())
           .decode()}
    d = data_dir() / "web"
    d.mkdir(parents=True, exist_ok=True)
    log = ("== Collecting the corpus from Warcraft Logs  [+3s]\n  183 ranked kills found (183 new)\n"
           "  [40/183] 300s, 20 players, 30 adds killed\n")
    for jid, status in (("abcd0f0a", "running"), ("abcd0f0b", "failed (exit 1)")):
        (d / f"job-{jid}.json").write_text(json.dumps({"args": ["prep", "3470", "--difficulty", "mythic"],
                                                       "result": "", "status": "running", "started": time.time()}))
        (d / f"job-{jid}.log").write_text(log)
        job = web.JOBS.get(jid)
        job["status"] = status
        web.JOBS.jobs[jid] = job
        out[f"job {status}"] = web.job_page(jid).decode()
        for f in (f"job-{jid}.json", f"job-{jid}.log"):
            (d / f).unlink()
    update.STATE["release"] = update.Release("9.9.9", "https://github.com", "", "https://github.com/x.exe", 1, "")
    out["banner"] = web.page("x", "").decode()
    update.STATE["release"] = None
    for f in sorted((data_dir() / "reports").glob("*.html")):
        out[f.name] = f.read_text(encoding="utf-8")
    return out


def ours(text: str, source: str) -> bool:
    """A text written in our code (not game data, names or numbers): a run of 3 of its words is in the source."""
    words = text.split()
    if len(words) < 3:
        return f">{text}<" in source or f'"{text}"' in source or f"'{text}'" in source
    return any(" ".join(words[i:i + 3]) in source for i in range(len(words) - 2))


def main() -> None:
    from pathlib import Path

    lang = sys.argv[1] if len(sys.argv) > 1 else "fr"
    src = Path(i18n.__file__).parent
    source = "\n".join(p.read_text(encoding="utf-8") for p in src.rglob("*.py") if "locale" not in p.parts)
    seen: Counter[str] = Counter()
    for html in pages().values():
        seen.update({t for t in i18n.untranslated(html, lang) if ours(t, source)})
    for text, n in seen.most_common():
        print(f"{n:3} | {text}")


if __name__ == "__main__":
    main()
