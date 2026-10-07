"""HTTPS for the whole app: Windows' own certificates, plus an up-to-date bundle (certifi).

A tester's prep failed with "certificate has expired" (issue #17): an out-of-date certificate store on Windows can
keep an expired root and build a chain through it. certifi's bundle gives OpenSSL a valid path too. Installed once
as urllib's default opener: every urlopen() of the app uses it.
"""

from __future__ import annotations

import ssl
import urllib.request

_done = False


def context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()  # the system's certificates
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass
    return ctx


def install() -> None:
    global _done
    if _done:
        return
    try:
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=context())))
    except (OSError, ssl.SSLError):
        return
    _done = True
