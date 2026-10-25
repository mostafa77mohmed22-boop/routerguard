"""اختبارات مراقب الإنترنت (ping مُmockة)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitors.internet_monitor as im
from monitors.internet_monitor import InternetMonitor


class FakeDB:
    def __init__(self):
        self.events = []
        self.outages = []

    def record_event(self, *args, **kwargs):
        self.events.append(args)
        return 1

    def record_outage(self, started, ended):
        self.outages.append((started, ended))
        return 1

    def list_outages(self, since):
        return [{"duration_sec": (e - s).total_seconds()}
                for s, e in self.outages if e >= since]


CFG = {"internet": {"enabled": True, "gateway": "192.168.1.1",
                    "dns_targets": ["8.8.8.8"],
                    "speedtest_enabled": False}}


def test_outage_start_and_end(monkeypatch):
    db = FakeDB()
    mon = InternetMonitor(db, CFG)
    monkeypatch.setattr(im, "ping", lambda host, timeout=2: None)
    r1 = mon.check(datetime(2026, 1, 1, 10, 0, 0))
    assert r1["online"] is False and r1["in_outage"] is True
    assert any(e[0] == "outage_start" for e in db.events)

    monkeypatch.setattr(im, "ping", lambda host, timeout=2: 12.5)
    r2 = mon.check(datetime(2026, 1, 1, 10, 7, 30))
    assert r2["online"] is True and r2["in_outage"] is False
    assert len(db.outages) == 1
    assert any(e[0] == "outage_end" for e in db.events)


def test_uptime_full_when_no_outages():
    db = FakeDB()
    mon = InternetMonitor(db, CFG)
    assert mon.uptime_percent(24) == 100.0


def test_uptime_reflects_outage():
    db = FakeDB()
    now = datetime.now()
    db.outages.append((now - timedelta(hours=2), now - timedelta(hours=1)))
    mon = InternetMonitor(db, CFG)
    assert mon.uptime_percent(24) == round(100 * 23 / 24, 2)


def test_ping_uses_milliseconds_on_windows(monkeypatch):
    """في ويندوز: -w بالمللي ثانية (2 ثوانٍ = 2000)."""
    import subprocess as sp
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = "Reply from 192.168.1.1: bytes=32 time=5ms TTL=64"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(im.platform, "system", lambda: "Windows")
    monkeypatch.setattr(im.subprocess, "run", fake_run)
    assert im.ping("192.168.1.1", timeout=2) == 5.0
    assert captured["cmd"][1:5] == ["-n", "1", "-w", "2000"]


def test_ping_uses_seconds_on_linux(monkeypatch):
    """في لينكس: -W بالثواني."""
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = "64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=3.2 ms"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(im.platform, "system", lambda: "Linux")
    monkeypatch.setattr(im.subprocess, "run", fake_run)
    assert im.ping("192.168.1.1", timeout=2) == 3.2
    assert captured["cmd"][1:5] == ["-c", "1", "-W", "2"]


def test_ping_returns_none_on_failure(monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(im.platform, "system", lambda: "Windows")
    monkeypatch.setattr(im.subprocess, "run", lambda *a, **k: FakeResult())
    assert im.ping("10.255.255.1", timeout=1) is None
