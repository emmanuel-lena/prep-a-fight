"""Read text from the system clipboard without extra dependencies."""

from __future__ import annotations

import shutil
import subprocess
import sys


def read_clipboard() -> str:
    if sys.platform == "win32":
        cmd = ["powershell", "-NoProfile", "-Command",
               "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"]
    elif sys.platform == "darwin":
        cmd = ["pbpaste"]
    elif shutil.which("wl-paste"):
        cmd = ["wl-paste", "--no-newline"]
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard", "-o"]
    else:
        cmd = None

    if cmd:
        out = subprocess.run(cmd, capture_output=True, timeout=15)
        if out.returncode == 0:
            return out.stdout.decode("utf-8", "replace")

    import tkinter  # fallback, stdlib but may be missing on minimal Linux installs

    root = tkinter.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    finally:
        root.destroy()
