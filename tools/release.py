"""Release the app: checks, version bump, commit, tag, push, then the GitHub pre-release once the installer is built.

    python tools/release.py 0.5.4 --message msg.txt --notes "What changed, for the players."
    python tools/release.py 0.5.4 --message msg.txt --notes "..." --dry-run   # the checks only

Every step stops the release at the first failure, before anything is committed, tagged or pushed when a check fails.
The working copy is never reset: line-ending noise (CRLF in files written on Windows) is cleaned only when it is the
only difference left after the commit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"


class Stop(Exception):
    pass


def run(*cmd: str, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not quiet and res.stdout.strip():
        print(res.stdout.strip()[-3000:])
    if check and res.returncode != 0:
        raise Stop(f"failed ({res.returncode}): {' '.join(cmd)}\n{(res.stdout + res.stderr).strip()[-3000:]}")
    return res


def current_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def parse(v: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise Stop(f"not a version: {v}")
    return tuple(int(x) for x in v.split("."))


def bump(version: str) -> None:
    p = ROOT / "pyproject.toml"
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig")  # never keep a byte order mark (tomllib refuses it)
    old = current_version()
    new = text.replace(f'version = "{old}"', f'version = "{version}"', 1)
    if new == text:
        raise Stop("the version line was not found in pyproject.toml")
    p.write_bytes(new.encode("utf-8"))  # bytes: no newline translation, no BOM
    if current_version() != version:
        raise Stop("pyproject.toml does not read back with the new version")
    # the app's own version (the updater compares it with the releases): the same, always
    init = ROOT / "src" / "paf" / "__init__.py"
    code = init.read_bytes().decode("utf-8-sig")
    code2 = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', code, count=1)
    if code2 == code and f'__version__ = "{version}"' not in code:
        raise Stop("__version__ was not found in src/paf/__init__.py")
    init.write_bytes(code2.encode("utf-8"))


def clean_line_endings() -> None:
    """After the commit, files written with CRLF can show as modified. Restore them only when line endings are the
    only difference; anything else is reported and left alone."""
    if not run("git", "status", "--porcelain", quiet=True).stdout.strip():
        return
    if run("git", "diff", "--ignore-cr-at-eol", "--quiet", check=False).returncode == 0:
        run("git", "checkout", "--", ".")
    else:
        print("WARNING: the working copy has real changes that are not in the release; left untouched.")


def wait_and_publish(tag: str, notes: str, timeout: float = 1200) -> None:
    run_id = ""
    for _ in range(30):
        out = run("gh", "run", "list", "--workflow", "release.yml", "--branch", tag, "--limit", "1",
                  "--json", "databaseId", "-q", ".[0].databaseId", quiet=True).stdout.strip()
        if out:
            run_id = out
            break
        time.sleep(4)
    if not run_id:
        raise Stop(f"no release build started for {tag}")
    res = subprocess.run(["gh", "run", "watch", run_id, "--exit-status"], cwd=ROOT, capture_output=True,
                         timeout=timeout)
    if res.returncode != 0:
        raise Stop(f"the release build of {tag} failed: gh run view {run_id} --log-failed")
    # exactly this version's installer: the app's updater downloads it by name
    assets = run("gh", "release", "view", tag, "--json", "assets", "-q", "[.assets[].name] | join(\",\")",
                 quiet=True).stdout.strip().split(",")
    expected = f"prep-a-fight-setup-{tag.removeprefix('v')}.exe"
    if assets != [expected]:
        raise Stop(f"the release {tag} holds {assets}, expected only {expected}: fix it before publishing")
    run("gh", "release", "edit", tag, "--draft=false", "--prerelease", "--title", tag.removeprefix("v"),
        "--notes", notes)
    view = run("gh", "release", "view", tag, "--json", "isDraft,assets", "-q",
               '"draft=\\(.isDraft) assets=\\([.assets[].name])"', quiet=True).stdout.strip()
    print(f"published {tag}: {view}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version")
    ap.add_argument("--message", help="file with the commit message (attribution lines included)")
    ap.add_argument("--notes", required=True, help="release notes for the players")
    ap.add_argument("--dry-run", action="store_true", help="run the checks only")
    ap.add_argument("--resume", action="store_true",
                    help="the commit and tag of this version are pushed but its publication stopped (a build that "
                         "failed for a network error and was run again): wait for the build and publish only")
    a = ap.parse_args()
    try:
        if a.resume:  # nothing is committed, tagged or pushed: the release of this version, already pushed
            if current_version() != a.version:
                raise Stop(f"the working copy is at {current_version()}, not {a.version}")
            if not run("git", "ls-remote", "--tags", "origin", f"v{a.version}", quiet=True).stdout.strip():
                raise Stop(f"the tag v{a.version} is not on origin: nothing to resume")
            wait_and_publish(f"v{a.version}", a.notes)
            return 0
        if not a.message:
            raise Stop("--message is needed")
        old, new = current_version(), a.version
        if parse(new) <= parse(old):
            raise Stop(f"{new} is not above the current version {old}")
        msg = Path(a.message)
        if not msg.is_file() or not msg.read_text(encoding="utf-8").strip():
            raise Stop(f"no commit message in {msg}")
        if run("git", "rev-parse", "--abbrev-ref", "HEAD", quiet=True).stdout.strip() != "main":
            raise Stop("not on main")
        if run("git", "tag", "-l", f"v{new}", quiet=True).stdout.strip() or \
                run("git", "ls-remote", "--tags", "origin", f"v{new}", quiet=True).stdout.strip():
            raise Stop(f"the tag v{new} already exists")
        # 1. checks: nothing is changed if they fail
        run(str(PY), "-m", "ruff", "check", ".")
        run(str(PY), "-m", "pytest", "-q", quiet=True)
        if a.dry_run:
            print("checks passed (dry run: nothing committed)")
            return 0
        # 2. version, commit: the commit must hold everything
        bump(new)
        run("git", "add", "-A")
        run("git", "commit", "-q", "-F", str(msg))
        in_project = run("git", "show", "HEAD:pyproject.toml", quiet=True).stdout.count(f'version = "{new}"') == 1
        in_app = f'__version__ = "{new}"' in run("git", "show", "HEAD:src/paf/__init__.py", quiet=True).stdout
        if not (in_project and in_app):
            raise Stop("the commit does not carry the new version")
        clean_line_endings()
        # 3. tag and push, then the pre-release once the installer is built
        run("git", "tag", f"v{new}")
        run("git", "push", "-q", "origin", "main")
        run("git", "push", "-q", "origin", f"v{new}")
        wait_and_publish(f"v{new}", a.notes)
        return 0
    except Stop as ex:
        print(f"\nRELEASE STOPPED: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
