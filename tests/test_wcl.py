import json

import pytest

from paf.wcl import API_URL, TOKEN_URL, WCLClient, WCLError


class FakeWCL:
    """Minimal fake of the token endpoint and the GraphQL endpoint."""

    def __init__(self, responses):
        self.responses = list(responses)  # (status, payload) for API calls, in order
        self.token_calls = 0
        self.api_bodies = []

    def __call__(self, url, body, headers):
        if url == TOKEN_URL:
            self.token_calls += 1
            assert headers["Authorization"].startswith("Basic ")
            token = {"access_token": f"tok{self.token_calls}", "expires_in": 31536000}
            return 200, json.dumps(token).encode()
        assert url == API_URL
        assert headers["Authorization"].startswith("Bearer tok")
        self.api_bodies.append(json.loads(body))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode()


def make(tmp_path, fake):
    return WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=fake, sleep=lambda s: None)


def test_query_and_token_cached_on_disk(tmp_path):
    fake = FakeWCL([(200, {"data": {"x": 1}}), (200, {"data": {"x": 2}})])
    assert make(tmp_path, fake).query("{ x }") == {"x": 1}
    # a new client reuses the token saved on disk
    assert make(tmp_path, fake).query("{ x }") == {"x": 2}
    assert fake.token_calls == 1


def test_response_cache(tmp_path):
    fake = FakeWCL([(200, {"data": {"x": 1}})])
    c = make(tmp_path, fake)
    assert c.query("{ x }", {"a": 1}, cache_ttl=0) == {"x": 1}
    assert c.query("{  x }", {"a": 1}, cache_ttl=0) == {"x": 1}  # whitespace-insensitive, no 2nd call
    assert len(fake.api_bodies) == 1
    assert "secret" not in "".join(p.read_text() for p in (tmp_path / "wcl").glob("*.json"))


def test_retry_on_rate_limit_and_server_error(tmp_path):
    fake = FakeWCL([(429, {}), (502, {}), (200, {"data": {"ok": True}})])
    assert make(tmp_path, fake).query("{ ok }") == {"ok": True}


def test_graphql_errors_raise(tmp_path):
    fake = FakeWCL([(200, {"errors": [{"message": "bad field"}]})])
    with pytest.raises(WCLError, match="bad field"):
        make(tmp_path, fake).query("{ nope }")


def test_expired_token_is_refreshed_once(tmp_path):
    fake = FakeWCL([(401, {}), (200, {"data": {"x": 1}})])
    assert make(tmp_path, fake).query("{ x }") == {"x": 1}
    assert fake.token_calls == 2


def test_events_pagination(tmp_path):
    def page(data, nxt):
        return 200, {"data": {"reportData": {"report": {"events": {"data": data, "nextPageTimestamp": nxt}}}}}

    fake = FakeWCL([page([{"t": 1}, {"t": 2}], 500), page([{"t": 3}], None)])
    events = list(make(tmp_path, fake).events("ABC", 5, 0, 1000, cache=False))
    assert [e["t"] for e in events] == [1, 2, 3]
    assert fake.api_bodies[1]["variables"]["start"] == 500
    assert fake.api_bodies[0]["variables"]["fightIDs"] == [5]


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("WCL_CLIENT_ID", raising=False)
    monkeypatch.delenv("WCL_CLIENT_SECRET", raising=False)
    with pytest.raises(WCLError):
        WCLClient()


def test_network_errors_are_retried(tmp_path):
    fake = FakeWCL([(599, {}), (200, {"data": {"ok": 1}})])
    assert make(tmp_path, fake).query("{ ok }") == {"ok": 1}


def test_a_used_up_quota_is_waited_for(tmp_path, capsys):
    # every retry refused (429), then the reset time is asked, the client waits, and the query goes through
    refused = [(429, {})] * 5
    fake = FakeWCL(refused + [(200, {"data": {"rateLimitData": {"pointsResetIn": 600}}}), (200, {"data": {"ok": 1}})])
    waits = []
    c = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=fake, sleep=waits.append)
    assert c.query("{ ok }") == {"ok": 1}
    assert 605 in waits and "quota used up" in capsys.readouterr().out


def test_a_quota_that_never_comes_back_still_fails(tmp_path):
    fake = FakeWCL([(429, {})] * 40)
    c = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=fake, sleep=lambda s: None)
    with pytest.raises(WCLError, match="429"):
        c.query("{ ok }")
