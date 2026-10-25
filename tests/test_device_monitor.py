"""اختبارات مراقب الأجهزة (بقاعدة بيانات وهمية)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.types import DeviceRow
from monitors.device_monitor import (
    ALLOWED, BLOCKED, UNKNOWN, VISITOR, DeviceMonitor,
)


class FakeDB:
    def __init__(self):
        self.devices = {}
        self.events = []

    def get_device(self, mac):
        return self.devices.get(mac)

    def upsert_device(self, mac, hostname, ip, status):
        is_new = mac not in self.devices
        self.devices[mac] = {"mac": mac, "hostname": hostname,
                             "ip": ip, "status": status, "present": 1}
        return 1, is_new

    def touch_seen(self, mac, at):
        pass

    def mark_device_left(self, mac, at):
        if mac in self.devices:
            self.devices[mac]["present"] = 0

    def update_device_status(self, mac, status):
        if mac in self.devices:
            self.devices[mac]["status"] = status

    def record_event(self, *args, **kwargs):
        self.events.append(args)
        return 1

    def set_vendor(self, mac, vendor):
        pass

    def list_devices(self, status=None):
        devs = list(self.devices.values())
        if status:
            devs = [d for d in devs if d["status"] == status]
        return devs


CFG = {
    "devices": {
        "allowed": ["MyPhone", "MyLaptop"],
        "allowed_macs": ["AA:BB:CC:DD:EE:FF"],
        "visitors": ["Guest-Phone"],
        "visitors_macs": [],
        "blacklist": [],
        "blacklist_macs": ["DE:AD:BE:EF:00:01"],
    }
}


def make_monitor(tmp_path):
    return DeviceMonitor(FakeDB(), CFG, data_dir=str(tmp_path))


def row(name, mac, ip="192.168.1.10"):
    return DeviceRow(hostname=name, ip=ip, mac=mac, raw=f"{name}|{ip}|{mac}")


def test_classify_allowed_by_name(tmp_path):
    m = make_monitor(tmp_path)
    assert m.classify(row("MyPhone", "11:22:33:44:55:66")) == ALLOWED
    assert m.classify(row("myphone", "11:22:33:44:55:66")) == ALLOWED  # غير حساس لحالة الأحرف


def test_classify_allowed_by_mac(tmp_path):
    m = make_monitor(tmp_path)
    assert m.classify(row("Whatever", "AA:BB:CC:DD:EE:FF")) == ALLOWED


def test_classify_visitor(tmp_path):
    m = make_monitor(tmp_path)
    assert m.classify(row("Guest-Phone", "11:22:33:44:55:77")) == VISITOR


def test_classify_blocked_by_mac(tmp_path):
    m = make_monitor(tmp_path)
    assert m.classify(row("Evil", "de:ad:be:ef:00:01")) == BLOCKED


def test_classify_unknown(tmp_path):
    m = make_monitor(tmp_path)
    assert m.classify(row("Stranger", "12:34:56:78:9A:BC")) == UNKNOWN


def test_evaluate_detects_intruder_and_new(tmp_path):
    m = make_monitor(tmp_path)
    rows = [row("MyPhone", "11:22:33:44:55:66"),
            row("Stranger", "12:34:56:78:9A:BC")]
    intruders, new_devices, spoofs = m.evaluate(rows)
    assert len(intruders) == 1 and intruders[0].hostname == "Stranger"
    assert len(new_devices) == 2
    assert spoofs == []
    # الفحص الثاني: لم يعد جديداً
    intruders2, new_devices2, _ = m.evaluate(rows)
    assert new_devices2 == []
    assert len(intruders2) == 1


def test_spoof_detection(tmp_path):
    db = FakeDB()
    db.devices["AA:BB:CC:00:11:22"] = {"mac": "AA:BB:CC:00:11:22",
                                      "hostname": "MyPhone", "ip": "x",
                                      "status": ALLOWED}
    m = DeviceMonitor(db, CFG, data_dir=str(tmp_path))
    _, _, spoofs = m.evaluate([row("MyPhone", "FF:EE:DD:CC:BB:AA")])
    assert len(spoofs) == 1
    assert "MyPhone" in spoofs[0]


def test_block_mac_persists(tmp_path):
    m = make_monitor(tmp_path)
    assert m.block_mac("12:34:56:78:9A:BC") is True
    assert m.block_mac("12:34:56:78:9A:BC") is False  # مكرر
    assert m.block_mac("not-a-mac") is False
    # نسخة جديدة من المراقب تقرأ الحظر من الملف
    m2 = DeviceMonitor(FakeDB(), CFG, data_dir=str(tmp_path))
    assert m2.classify(row("X", "12:34:56:78:9A:BC")) == BLOCKED
    assert m2.unblock_mac("12:34:56:78:9A:BC") is True
    m3 = DeviceMonitor(FakeDB(), CFG, data_dir=str(tmp_path))
    assert m3.classify(row("X", "12:34:56:78:9A:BC")) == UNKNOWN


def test_device_left_recorded_when_missing(tmp_path):
    """جهاز كان متصلاً واختفى → حدث device_left و present=0."""
    m = make_monitor(tmp_path)
    rows = [row("MyPhone", "11:22:33:44:55:66"),
            row("Guest-Phone", "12:34:56:78:9A:BC")]
    m.evaluate(rows)
    assert m.db.devices["11:22:33:44:55:66"]["present"] == 1

    # الفحص الثاني: MyPhone اختفى
    m.evaluate([row("Guest-Phone", "12:34:56:78:9A:BC")])
    assert m.db.devices["11:22:33:44:55:66"]["present"] == 0
    left_events = [e for e in m.db.events if e[0] == "device_left"]
    assert len(left_events) == 1
    assert "11:22:33:44:55:66" in left_events[0][2]  # الرسالة تذكر الـ MAC


def test_no_duplicate_left_events(tmp_path):
    """الجهاز الغائب لا يُسجَّل مغادرته مرتين."""
    m = make_monitor(tmp_path)
    m.evaluate([row("MyPhone", "11:22:33:44:55:66")])
    m.evaluate([])  # غادر
    m.evaluate([])  # ما زال غائباً — لا حدث جديد
    left_events = [e for e in m.db.events if e[0] == "device_left"]
    assert len(left_events) == 1


def test_device_rejoin_marks_present_again(tmp_path):
    """جهاز غادر ثم عاد → present=1 مجدداً."""
    m = make_monitor(tmp_path)
    m.evaluate([row("MyPhone", "11:22:33:44:55:66")])
    m.evaluate([])
    assert m.db.devices["11:22:33:44:55:66"]["present"] == 0
    m.evaluate([row("MyPhone", "11:22:33:44:55:66")])
    assert m.db.devices["11:22:33:44:55:66"]["present"] == 1
