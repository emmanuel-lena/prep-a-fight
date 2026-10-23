import threading

from paf import tray


def test_a_done_prep_s_notification_stays_until_the_app_is_in_front(monkeypatch):
    # issue #33: the notification's icon went after a minute, its notification with it, while Windows held it back
    # during a game; it now stays until the app's window comes to the front, and the taskbar button blinks
    closed, flashed, fronts = threading.Event(), [], iter([False, False, True])

    class FakeTray:
        def __init__(self, *a, **k):
            pass

        def notify(self, title, text):
            self.said = title

        def close(self):
            closed.set()

    monkeypatch.setattr(tray.sys, "platform", "win32")
    monkeypatch.setattr(tray, "Tray", FakeTray)
    monkeypatch.setattr(tray, "flash", flashed.append)
    monkeypatch.setattr(tray, "in_front", lambda title: next(fronts, True))
    tray.notify_once("Nek'zali is ready", "Your prep sheet is waiting.", "prep-a-fight", poll=0.01)
    assert closed.wait(2) and flashed == ["prep-a-fight"]
