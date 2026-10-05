"""The desktop app: the local web app in its own window (pywebview, on the WebView2 engine Windows ships),
without a console or a browser tab. Falls back to the browser when pywebview is missing."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from paf.config import data_dir, load_dotenv

TITLE = "prep-a-fight"
ICON = Path(__file__).parent / "assets" / "prep-a-fight.ico"


def _quiet_streams() -> None:
    """Started without a console (pythonw), print() and tracebacks need somewhere to go."""
    if sys.stdout is None or sys.stderr is None:
        log_dir = data_dir() / "web"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives with the app
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def _own_taskbar_icon() -> None:
    """Run under pythonw.exe, the window would be grouped with Python and show its icon in the taskbar."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("prep-a-fight.app")
        except (AttributeError, OSError):
            pass


def main() -> int:
    _quiet_streams()
    load_dotenv()
    _own_taskbar_icon()
    from paf import web
    from paf.simc_install import ensure_simc

    ensure_simc()  # first launch of an installed copy: SimulationCraft downloads while the player sets up

    server = web.Server(("127.0.0.1", 0), web.Handler)  # a free port: several copies never collide
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        import webview
    except ImportError:
        import webbrowser

        print(f"pywebview is not installed: prep-a-fight opens in your browser ({url}). Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    try:
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # Wowhead / Warcraft Logs links
    except (AttributeError, TypeError):
        pass
    webview.create_window(TITLE, url, width=1320, height=920, min_size=(900, 600), background_color="#181219")
    webview.start(icon=str(ICON) if ICON.is_file() else None)
    server.shutdown()
    server.server_close()
    try:
        from paf.cache import prune_all

        prune_all()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
