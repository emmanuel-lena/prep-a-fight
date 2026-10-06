from paf import inproc


def test_pages_are_served_in_process(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    status, reason, headers, body = inproc.serve("GET", "/settings")
    assert status == 200 and b"Settings" in body and ("Content-Type", "text/html; charset=utf-8") in headers
    status, reason, headers, body = inproc.serve(
        "POST", "/language", {"Content-Type": "application/x-www-form-urlencoded", "Referer": "http://paf.local/tools"},
        b"lang=en")
    assert status == 303 and ("Location", "/tools") in headers
    s, h, page = inproc.as_page(status, headers, body)  # a redirect becomes a page that goes there
    assert s == 200 and b'url=/tools' in page and b"location.replace('/tools')" in page
    assert inproc.serve("GET", "/nope")[0] == 404
