import json

import pytest

from paf.wcl import API_URL, TOKEN_URL, WCLClient, WCLError


@pytest.fixture(autouse=True)
def own_data_dir(tmp_path, monkeypatch):
    """The client writes the quota it reads in the data folder: never the real one."""
    monkeypatch.setenv("PAF_HOME", str(tmp_path / "home"))


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


def test_a_quota_that_never_comes_back_still_fails(tmp_path, capsys):
    from paf.wcl import QUOTA_FALLBACK_WAIT, QUOTA_WAITS

    fake = FakeWCL([(429, {})] * 400)
    waits = []
    c = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=fake, sleep=waits.append)
    with pytest.raises(WCLError, match="429"):
        c.query("{ ok }")
    assert waits.count(QUOTA_FALLBACK_WAIT) == QUOTA_WAITS and QUOTA_WAITS * QUOTA_FALLBACK_WAIT >= 3600
    assert capsys.readouterr().out.count("quota used up") == 1  # said once, not at every short wait


def test_a_used_up_quota_waits_until_the_reset_read_earlier(tmp_path, capsys):
    # the reset time was read a while ago; once the quota is used up, asking it again is refused too
    fake = FakeWCL([(200, {"data": {"rateLimitData": {"limitPerHour": 3600, "pointsSpentThisHour": 3500,
                                                      "pointsResetIn": 1500}}})]
                   + [(429, {})] * 6 + [(200, {"data": {"ok": 1}})])
    waits = []
    c = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=fake, sleep=waits.append)
    c.rate_limit()
    assert c.query("{ ok }") == {"ok": 1}
    quota_wait = [w for w in waits if w > 60]
    assert quota_wait and 1450 <= quota_wait[0] <= 1510  # the remaining 25 min, not the fallback 15


def test_a_page_never_waits_for_the_quota(tmp_path, monkeypatch):
    from paf import wcl

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setitem(wcl.INTERACTIVE, "on", True)
    waits = []
    c = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=FakeWCL([(429, {})]), sleep=waits.append)
    with pytest.raises(WCLError, match="quota is used up"):
        c.query("{ ok }")
    assert waits == []  # said at once, no sleep


def test_a_refused_query_answers_from_its_old_cache(tmp_path):
    fake = FakeWCL([(200, {"data": {"zones": [1]}}), (429, {})] + [(429, {})] * 200)
    c = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=fake, sleep=lambda s: None,
                  wait_for_quota=False)
    assert c.query("{ zones }", cache_ttl=1) == {"zones": [1]}
    import os
    import time

    for f in (tmp_path / "wcl").glob("*.json"):  # the cached answer is now stale
        os.utime(f, (time.time() - 3600, time.time() - 3600))
    assert c.query("{ zones }", cache_ttl=1) == {"zones": [1]}


def test_the_reset_read_by_a_prep_is_said_by_a_page(tmp_path, monkeypatch):
    from paf import wcl

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    prep = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", transport=FakeWCL(
        [(200, {"data": {"rateLimitData": {"limitPerHour": 3600, "pointsSpentThisHour": 3600,
                                           "pointsResetIn": 1200}}})]), sleep=lambda s: None)
    prep.rate_limit()
    assert "comes back around" in wcl.quota_sentence()


def test_an_estimate_knows_the_quota_is_used_up_without_waiting(tmp_path, monkeypatch):
    from paf import wcl

    monkeypatch.setitem(wcl.INTERACTIVE, "on", True)
    prep = WCLClient("id", "secret", cache_dir=tmp_path / "wcl", sleep=lambda s: None, wait_for_quota=True,
                     transport=FakeWCL([(200, {"data": {"rateLimitData": {
                         "limitPerHour": 3600, "pointsSpentThisHour": 3000, "pointsResetIn": 1200}}})]))
    prep.rate_limit()  # a prep read it 10 kills ago
    page = WCLClient("id", "secret", cache_dir=tmp_path / "wcl2", transport=FakeWCL([(429, {})]))
    monkeypatch.setattr(wcl, "QUOTA_FRESH", 0.0)  # the read is old: the page asks
    left, reset = wcl.quota_left(page)
    assert left == 0.0 and 19 <= reset <= 20  # used up now, back in the 20 minutes the prep read
    monkeypatch.setattr(wcl, "QUOTA_FRESH", 120.0)  # recent: refused once, said by the shared read (issue #30)
    assert wcl.quota_left(page)[0] == 0.0 and wcl.fresh_quota()["spent"] == 3600
