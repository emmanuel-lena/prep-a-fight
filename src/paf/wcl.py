"""Warcraft Logs API v2 client (GraphQL): the player's own API key (OAuth2 client credentials), else their
Warcraft Logs login (paf.wcllogin, the user endpoint).

- The access token is cached on disk until shortly before it expires.
- Responses can be cached on disk (reports never change once uploaded); the token is never part
  of the cache key and never written to logs.
- ``events()`` follows ``nextPageTimestamp`` until the requested window is exhausted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from paf.config import data_dir

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"
USER_API_URL = "https://www.warcraftlogs.com/api/v2/user"
USER_AGENT = "prep-a-fight (+https://github.com/emmanuel-lena/prep-a-fight)"

# transport(url, body, headers) -> (status, response bytes); replaced in tests
Transport = Callable[[str, bytes, dict[str, str]], tuple[int, bytes]]


class WCLError(RuntimeError):
    pass


def _urllib_transport(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        # network hiccup: reported as a server error so the caller retries with backoff
        return 599, str(e).encode()


QUOTA_WAITS = 2  # a query waits at most this many quota resets before failing
QUOTA_FALLBACK_WAIT = 900.0  # seconds to wait when the reset time cannot be read


class WCLClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        cache_dir: Path | None = None,
        transport: Transport | None = None,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client_id = client_id or os.environ.get("WCL_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("WCL_CLIENT_SECRET", "")
        self.user = False  # queries go through the player's Warcraft Logs login (paf.wcllogin)
        if not (self.client_id and self.client_secret):
            from paf import wcllogin

            if client_id is None and wcllogin.logged_in():
                self.user = True
            else:
                raise WCLError("Not connected to Warcraft Logs: connect in Settings (or set WCL_CLIENT_ID / "
                               "WCL_CLIENT_SECRET, see `paf doctor`)")
        self.api_url = USER_API_URL if self.user else API_URL
        self.cache_dir = cache_dir or data_dir() / "cache" / "wcl"
        self.transport = transport or _urllib_transport
        self.max_retries = max_retries
        self.sleep = sleep
        self._token: str | None = None
        self._token_expires = 0.0

    # --- auth ---------------------------------------------------------------------------------

    def _token_file(self) -> Path:
        # one file per client id, so switching keys never reuses another client's token
        tag = hashlib.sha256(self.client_id.encode()).hexdigest()[:12]
        return self.cache_dir.parent / f"wcl_token_{tag}.json"

    def token(self) -> str:
        if self.user:
            from paf import wcllogin

            return wcllogin.token(self.transport)
        now = time.time()
        if self._token and now < self._token_expires:
            return self._token
        f = self._token_file()
        if f.is_file():
            try:
                saved = json.loads(f.read_text(encoding="utf-8"))
                if now < saved["expires_at"]:
                    self._token, self._token_expires = saved["access_token"], saved["expires_at"]
                    return self._token
            except (ValueError, KeyError):
                pass

        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        status, raw = self.transport(
            TOKEN_URL,
            urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        if status != 200:
            raise WCLError(f"token request failed: HTTP {status}")
        payload = json.loads(raw)
        self._token = payload["access_token"]
        # refresh one hour early
        self._token_expires = now + max(60.0, float(payload.get("expires_in", 3600)) - 3600)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"access_token": self._token, "expires_at": self._token_expires}),
                     encoding="utf-8")
        return self._token

    # --- queries ------------------------------------------------------------------------------

    def _cache_path(self, query: str, variables: dict[str, Any]) -> Path:
        key = json.dumps({"q": " ".join(query.split()), "v": variables}, sort_keys=True)
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def query(self, query: str, variables: dict[str, Any] | None = None,
              cache_ttl: float | None = None) -> dict[str, Any]:
        """Run a GraphQL query and return its ``data``.

        cache_ttl: None = no cache, 0 = cache forever, >0 = seconds.
        """
        variables = variables or {}
        cache_file = self._cache_path(query, variables) if cache_ttl is not None else None
        if cache_file and cache_file.is_file():
            age = time.time() - cache_file.stat().st_mtime
            if cache_ttl == 0 or age < cache_ttl:
                return json.loads(cache_file.read_text(encoding="utf-8"))

        body = json.dumps({"query": query, "variables": variables}).encode()
        delay = 2.0
        quota_waits = 0
        attempt = -1
        while attempt < self.max_retries:
            attempt += 1
            status, raw = self.transport(
                self.api_url, body,
                {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"},
            )
            if status == 401 and attempt == 0:
                if self.user:
                    from paf import wcllogin

                    wcllogin.refresh(self.transport)
                else:
                    self._token = None
                    self._token_file().unlink(missing_ok=True)
                continue
            if status == 429 and attempt == self.max_retries and quota_waits < QUOTA_WAITS:
                # the hourly quota is used up: wait for its reset instead of failing every query until then
                wait = self._quota_reset()
                print(f"  Warcraft Logs quota used up for this hour: waiting {max(1, round(wait / 60))} min for "
                      f"its reset, then the prep goes on by itself...", flush=True)
                self.sleep(wait)
                quota_waits += 1
                attempt, delay = -1, 2.0
                continue
            if status == 429 or status >= 500:
                if attempt == self.max_retries:
                    raise WCLError(f"WCL API unavailable: HTTP {status}")
                self.sleep(delay)
                delay *= 2
                continue
            break
        if status != 200:
            raise WCLError(f"WCL API error: HTTP {status}: {raw[:300]!r}")

        payload = json.loads(raw)
        if payload.get("errors"):
            msgs = "; ".join(e.get("message", "?") for e in payload["errors"])
            raise WCLError(f"GraphQL error: {msgs}")
        data = payload.get("data") or {}
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _quota_reset(self) -> float:
        """Seconds until the hourly quota resets (asked directly: the query itself may be refused)."""
        q = json.dumps({"query": "{ rateLimitData { pointsResetIn } }"}).encode()
        try:
            status, raw = self.transport(self.api_url, q, {"Authorization": f"Bearer {self.token()}",
                                                      "Content-Type": "application/json"})
            if status == 200:
                left = float(json.loads(raw)["data"]["rateLimitData"]["pointsResetIn"])
                return min(3600.0, max(30.0, left + 5))
        except (ValueError, KeyError, TypeError, OSError):
            pass
        return QUOTA_FALLBACK_WAIT

    def rate_limit(self) -> dict[str, Any]:
        q = "{ rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn } }"
        return self.query(q)["rateLimitData"]

    # --- report events ------------------------------------------------------------------------

    EVENTS_QUERY = """
    query($code: String!, $fightIDs: [Int], $start: Float, $end: Float, $dataType: EventDataType,
          $hostility: HostilityType, $sourceID: Int, $targetID: Int, $abilityID: Float,
          $filter: String, $limit: Int, $res: Boolean) {
      reportData { report(code: $code) {
        events(fightIDs: $fightIDs, startTime: $start, endTime: $end, dataType: $dataType,
               hostilityType: $hostility, sourceID: $sourceID, targetID: $targetID,
               abilityID: $abilityID, filterExpression: $filter, limit: $limit,
               includeResources: $res) {
          data nextPageTimestamp
        }
      } }
    }
    """

    def events(self, code: str, fight_id: int, start: float, end: float, *,
               data_type: str = "All", hostility: str = "Friendlies", source_id: int | None = None,
               target_id: int | None = None, ability_id: int | None = None,
               filter_expression: str | None = None, limit: int = 10000,
               include_resources: bool = False, cache: bool = True) -> Iterator[dict[str, Any]]:
        """Yield every event of a fight window, following ``nextPageTimestamp``."""
        page_start = start
        while True:
            variables = {
                "code": code, "fightIDs": [fight_id], "start": page_start, "end": end,
                "dataType": data_type, "hostility": hostility, "sourceID": source_id,
                "targetID": target_id, "abilityID": ability_id, "filter": filter_expression,
                "limit": limit, "res": include_resources or None,
            }
            variables = {k: v for k, v in variables.items() if v is not None}
            data = self.query(self.EVENTS_QUERY, variables, cache_ttl=0 if cache else None)
            page = data["reportData"]["report"]["events"]
            yield from page.get("data") or []
            nxt = page.get("nextPageTimestamp")
            if not nxt or nxt >= end or nxt <= page_start:
                return
            page_start = nxt
