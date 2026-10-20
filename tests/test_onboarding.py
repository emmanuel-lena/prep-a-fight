

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
