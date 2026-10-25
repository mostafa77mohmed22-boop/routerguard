"""اختبارات قاعدة البيانات SQLite على قاعدة مؤقتة."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from core.types import DeviceRow
from storage.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    yield database
    database.close()


def test_upsert_device_new_then_existing(db):
    dev_id, is_new = db.upsert_device("AA:BB:CC:DD:EE:FF", "PC1", "192.168.1.5", "trusted")
    assert is_new is True
    dev_id2, is_new2 = db.upsert_device("AA:BB:CC:DD:EE:FF", "PC1-renamed", "192.168.1.6", "trusted")
    assert is_new2 is False
    assert dev_id2 == dev_id
    row = db.get_device("AA:BB:CC:DD:EE:FF")
    assert row["ip"] == "192.168.1.6"
    assert row["hostname"] == "PC1-renamed"


def test_touch_seen_and_status_and_vendor(db):
    db.upsert_device("AA:BB:CC:DD:EE:FF", "PC1", "192.168.1.5", "unknown")
    later = datetime.now() + timedelta(hours=1)
    db.touch_seen("AA:BB:CC:DD:EE:FF", later)
    db.update_device_status("AA:BB:CC:DD:EE:FF", "blocked")
    db.set_vendor("AA:BB:CC:DD:EE:FF", "Apple")
    row = db.get_device("AA:BB:CC:DD:EE:FF")
    assert row["status"] == "blocked"
    assert row["vendor"] == "Apple"
    assert row["last_seen"] >= row["first_seen"]
    assert db.get_device("00:00:00:00:00:00") is None
    assert len(db.list_devices()) == 1
    assert len(db.list_devices(status="blocked")) == 1
    assert len(db.list_devices(status="trusted")) == 0


def test_record_scan(db):
    rows = [DeviceRow(hostname="a", ip="1.1.1.1", mac="AA:AA:AA:AA:AA:AA")]
    scan_id = db.record_scan(datetime.now(), rows, intruder_count=0)
    assert scan_id > 0


def test_record_scan_with_duration(db):
    rows = [DeviceRow(hostname="a", ip="1.1.1.1", mac="AA:AA:AA:AA:AA:AA")]
    db.record_scan(datetime.now(), rows, intruder_count=0, duration_ms=12345)
    assert db.last_scan_duration_ms() == 12345


def test_migration_adds_columns_to_old_db(tmp_path):
    """قاعدة بيانات قديمة (بدون present/duration_ms) → الترحيل يضيفهما."""
    import sqlite3
    old_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(old_path)
    conn.executescript("""
        CREATE TABLE scans (id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL, device_count INT NOT NULL DEFAULT 0,
            intruder_count INT NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
        CREATE TABLE devices (id INTEGER PRIMARY KEY AUTOINCREMENT,
            mac TEXT UNIQUE NOT NULL, hostname TEXT NOT NULL DEFAULT '',
            ip TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '',
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT '');
        INSERT INTO devices (mac, hostname, ip, status, first_seen, last_seen)
            VALUES ('AA:BB:CC:DD:EE:FF', 'PC1', '1.1.1.1', 'allowed',
                    '2026-01-01T00:00:00', '2026-01-02T00:00:00');
    """)
    conn.commit()
    conn.close()

    db = Database(old_path)
    try:
        dev = db.get_device("AA:BB:CC:DD:EE:FF")
        assert dev["present"] == 1  # القيمة الافتراضية للبيانات الموجودة
        db.mark_device_left("AA:BB:CC:DD:EE:FF", datetime.now())
        assert db.get_device("AA:BB:CC:DD:EE:FF")["present"] == 0
        db.upsert_device("AA:BB:CC:DD:EE:FF", "PC1", "1.1.1.1", "allowed")
        assert db.get_device("AA:BB:CC:DD:EE:FF")["present"] == 1
        assert db.last_scan_duration_ms() is None  # لا فحوصات بعد
    finally:
        db.close()


def test_mark_device_left_keeps_last_seen(db):
    db.upsert_device("AA:BB:CC:DD:EE:FF", "PC1", "192.168.1.5", "allowed")
    before = db.get_device("AA:BB:CC:DD:EE:FF")
    db.mark_device_left("AA:BB:CC:DD:EE:FF", datetime.now())
    after = db.get_device("AA:BB:CC:DD:EE:FF")
    assert after["present"] == 0
    assert after["last_seen"] == before["last_seen"]  # آخر ظهور محفوظ
    # mark ثانية لا تغير شيئاً (idempotent)
    db.mark_device_left("AA:BB:CC:DD:EE:FF", datetime.now())
    assert db.get_device("AA:BB:CC:DD:EE:FF")["present"] == 0


def test_events(db):
    eid = db.record_event("intruder", "critical", "جهاز دخيل", mac="AA:BB:CC:DD:EE:FF",
                          extra={"ip": "192.168.1.9"})
    assert eid > 0
    db.record_event("scan_ok", "info", "فحص سليم")
    events = db.list_events(limit=10)
    assert len(events) == 2
    assert events[0]["message"] == "فحص سليم"  # الأحدث أولاً
    recent = db.list_events(since=datetime.now() - timedelta(minutes=1))
    assert len(recent) == 2
    old = db.list_events(since=datetime.now() + timedelta(minutes=1))
    assert old == []


def test_outage_duration(db):
    start = datetime(2026, 10, 10, 3, 0, 0)
    end = datetime(2026, 10, 10, 3, 7, 30)
    oid = db.record_outage(start, end)
    assert oid > 0
    outages = db.list_outages(since=datetime(2026, 10, 1))
    assert len(outages) == 1
    assert outages[0]["duration_sec"] == 450


def test_speed(db):
    now = datetime.now()
    db.record_speed(now, 95.5, 20.1, 12.3)
    hist = db.speed_history(since=now - timedelta(hours=1))
    assert len(hist) == 1
    assert hist[0]["down_mbps"] == 95.5


def test_prune_keeps_recent_deletes_old(db):
    old = datetime.now() - timedelta(days=100)
    db.record_event("old", "info", "قديم", at=old)
    db.record_event("new", "info", "جديد")
    db.record_scan(old, [], 0)
    db.record_speed(old, 1, 1, 1)
    db.record_outage(old, old + timedelta(minutes=1))
    counts = db.prune(retention_days=90)
    assert counts["events"] == 1
    assert counts["scans"] == 1
    assert counts["speed"] == 1
    assert counts["outages"] == 1
    assert len(db.list_events()) == 1
    assert db.list_events()[0]["message"] == "جديد"


def test_daily_summary(db):
    today = date.today()
    db.upsert_device("AA:BB:CC:DD:EE:FF", "PC", "1.1.1.1", "trusted")
    db.record_event("intruder", "critical", "x")
    db.record_event("scan_ok", "info", "y")
    db.record_scan(datetime.now(), [], 0)
    now = datetime.now()
    db.record_speed(now, 100.0, 20.0, 10.0)
    db.record_outage(now - timedelta(hours=2), now - timedelta(hours=2) + timedelta(minutes=30))
    s = db.daily_summary(today)
    assert s["new_devices"] == 1
    assert s["events_by_severity"] == {"critical": 1, "info": 1}
    assert s["outages"] == 1
    assert s["outage_minutes"] == 30.0
    assert s["avg_down"] == 100.0
    assert s["scans"] == 1
