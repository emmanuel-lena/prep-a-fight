from paf import telemetry

LOG = """Ixuu (C:\\Users\\Manu\\AppData\\paf\\profiles\\ixuu.simc); fights: dummy 1 target 3 min
== What to equip  [+3s]
Pass 1: 236 single swaps x 1 fight(s)
  dummy 1 target 3 min: 95s
  kept: armor: 4; finger: 5
== Done  [+400s]
Traceback (most recent call last):
  File "x.py", line 1, in <module>
ValueError: boom
"""


def test_a_run_summary_carries_measures_never_a_name(monkeypatch):
    # the owner (2026-10-25): what is slow or broken on players' computers, opt-in, nothing personal
    args = ["gear", "--profile", "C:/Users/Manu/ixuu.simc", "--raid", "https://www.warcraftlogs.com/reports/AbC123",
            "--targets", "5"]
    assert telemetry.command(args) == "gear --profile --raid --targets"
    title, body = telemetry.summary(args, "failed (exit 1)", LOG, 401)
    assert title == "[run] gear failed" and "Outcome: failed (exit 1) in 401 s" in body
    assert "Pass 1: 236 single swaps" in body and "kept: armor: 4" in body and "ValueError: boom" in body
    assert "Ixuu" not in body and "Manu" not in body and "AbC123" not in body


def test_nothing_is_sent_unless_turned_on(monkeypatch):
    monkeypatch.setenv("PAF_TELEMETRY_URL", "https://discord.com/api/webhooks/x")
    monkeypatch.setattr(telemetry.settings, "get", lambda k: "off")
    assert not telemetry.enabled()
    monkeypatch.setattr(telemetry.settings, "get", lambda k: "on")
    assert telemetry.enabled()
    monkeypatch.delenv("PAF_TELEMETRY_URL")
    monkeypatch.setattr(telemetry, "URL_FILE", telemetry.Path("/nonexistent"))
    assert not telemetry.enabled()  # no channel built in: never
