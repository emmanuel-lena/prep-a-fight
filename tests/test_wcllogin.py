import base64
import hashlib
import json
import time
import urllib.parse

import pytest

from paf import wcllogin
from paf.wcl import USER_API_URL, WCLClient, WCLError


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.delenv("WCL_CLIENT_ID", raising=False)
    monkeypatch.delenv("WCL_CLIENT_SECRET", raising=False)
    return tmp_path


def test_authorize_url_carries_the_challenge_of_the_verifier():
    url = wcllogin.authorize_url("pub", "st", "verifier-123")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    expected = base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123").digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expected and q["code_challenge_method"] == "S256"
    assert q["client_id"] == "pub" and q["state"] == "st" and q["redirect_uri"] == wcllogin.REDIRECT
    assert "client_secret" not in q


def test_exchange_saves_the_login(home):
    sent = {}

    def fake(url, body, headers):
        sent.update(urllib.parse.parse_qsl(body.decode()))
        return 200, json.dumps({"access_token": "A", "refresh_token": "R", "expires_in": 7200}).encode()

    wcllogin.exchange("code", "ver", "pub", transport=fake)
    assert sent["grant_type"] == "authorization_code" and sent["code_verifier"] == "ver"
    saved = wcllogin.load()
    assert saved["access_token"] == "A" and saved["refresh_token"] == "R" and saved["client_id"] == "pub"


def test_client_uses_the_login_on_the_user_endpoint(home):
    wcllogin._save({"access_token": "A", "refresh_token": "R", "expires_in": 7200}, "pub")
    calls = []

    def fake(url, body, headers):
        calls.append((url, headers.get("Authorization")))
        return 200, json.dumps({"data": {"rateLimitData": {"limitPerHour": 3600}}}).encode()

    c = WCLClient(cache_dir=home / "wcl", transport=fake, sleep=lambda s: None)
    assert c.user and c.rate_limit()["limitPerHour"] == 3600
    assert calls == [(USER_API_URL, "Bearer A")]


def test_an_expiring_login_is_refreshed(home):
    wcllogin._save({"access_token": "old", "refresh_token": "R", "expires_in": 60}, "pub")

    def fake(url, body, headers):
        if url.endswith("/oauth/token"):
            form = dict(urllib.parse.parse_qsl(body.decode()))
            assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "R"
            return 200, json.dumps({"access_token": "new", "expires_in": 7200}).encode()
        assert headers["Authorization"] == "Bearer new"
        return 200, json.dumps({"data": {"rateLimitData": {}}}).encode()

    WCLClient(cache_dir=home / "wcl", transport=fake, sleep=lambda s: None).rate_limit()
    saved = wcllogin.load()
    assert saved["access_token"] == "new" and saved["refresh_token"] == "R" and saved["expires_at"] > time.time()


def test_without_key_nor_login_the_client_says_how_to_connect(home):
    with pytest.raises(WCLError, match="Not connected"):
        WCLClient(cache_dir=home / "wcl")


def test_logout_forgets_the_login(home):
    from paf.web import has_credentials

    wcllogin._save({"access_token": "A", "expires_in": 7200}, "pub")
    assert has_credentials()
    wcllogin.logout()
    assert not has_credentials()


def test_a_sim_waits_for_the_simc_the_app_is_downloading(home, monkeypatch):
    from paf import simc_install

    root = home / "simc"
    root.mkdir()
    (root / ".installing").write_text("1")
    exe = root / "1210.01.abc" / "simc.exe"
    ticks = []

    def sleep(s):  # the app's download ends during the wait
        ticks.append(s)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("")

    monkeypatch.setattr("time.sleep", sleep)
    monkeypatch.setattr(simc_install, "install_nightly", lambda: pytest.fail("downloaded twice"))
    assert simc_install.wait_for_simc() == exe and ticks


def test_a_half_extracted_simc_is_never_picked(home):
    from paf import simc_install

    half = home / "simc" / ("1210.02.new" + simc_install.PARTIAL) / "simc.exe"
    half.parent.mkdir(parents=True)
    half.write_text("")
    assert simc_install.find_simc() is None or simc_install.find_simc().parent != half.parent
