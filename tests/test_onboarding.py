

def test_the_accounts_characters_one_click_each(monkeypatch):
    """Issue #11: logged in with Warcraft Logs, the first run lists the account's characters to add, several at once."""
    from paf import onboarding, wcllogin

    data = {"userData": {"currentUser": {"characters": [
        {"name": "Alpha", "server": {"slug": "archimonde", "region": {"slug": "EU"}}},
        {"name": "Beta", "server": {"slug": "hyjal", "region": {"slug": "eu"}}},
        {"name": "NoServer", "server": None}]}}}
    assert onboarding.characters_of(data) == [("Alpha", "archimonde", "eu"), ("Beta", "hyjal", "eu")]

    class Client:
        def query(self, q, v, cache_ttl=0):
            return data
    monkeypatch.setattr(wcllogin, "logged_in", lambda: True)
    assert onboarding.account_characters(Client())[0] == ("Alpha", "archimonde", "eu")
    monkeypatch.setattr(wcllogin, "logged_in", lambda: False)
    assert onboarding.account_characters(Client()) == []  # the search by name stays
    monkeypatch.setattr(onboarding, "account_characters", lambda client=None: [("Alpha", "archimonde", "eu")])
    html = onboarding.page_body()
    assert "data-tab='acc'>Your account</button>" in html and "data-stay='1'" in html
    assert "Add Alpha <small>archimonde-EU</small>" in html


def test_connecting_stays_on_the_key_step(monkeypatch, tmp_path):
    """Issue #31: back from the browser, the player found the next step; the page now reloads on the key step."""
    from paf import onboarding, wcllogin

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    assert "wcl-connected" not in onboarding.JS  # no handler: paf.web.CONNECT_JS reloads the page
    monkeypatch.setattr(wcllogin, "logged_in", lambda: True)
    monkeypatch.setattr(onboarding, "account_characters", lambda client=None: [])
    html = onboarding.page_body()
    assert "Warcraft Logs: ready" in html and "an API key of your own is not needed" in html
