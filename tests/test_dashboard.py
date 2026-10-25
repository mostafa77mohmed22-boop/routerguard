"""اختبارات لوحة تحكم RouterGuard.

تستخدم FakeController يطبّق واجهة الـ controller ببيانات وهمية،
ثم تتحقق من مسارات Flask عبر test client.

التشغيل من جذر المشروع:
    python -m pytest tests/test_dashboard.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from flask import Flask

# إتاحة استيراد حزمة dashboard من جذر المشروع
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import create_app  # noqa: E402


class FakeController:
    """محاكاة بسيطة لواجهة الـ controller ببيانات وهمية ثابتة."""

    def get_status(self) -> dict:
        return {
            "router_ok": True,
            "last_scan": "2026-10-10 17:00:00",
            "internet_ok": True,
            "counts": {"total": 5, "allowed": 3, "visitor": 1, "unknown": 1, "blocked": 0},
            "uptime_24h": 99.2,
            "pending_escalations": 2,
        }

    def list_devices(self) -> list[dict]:
        return [
            {
                "mac": "AA:BB:CC:DD:EE:01",
                "hostname": "laptop-home",
                "ip": "192.168.1.10",
                "status": "allowed",
                "vendor": "Intel",
                "first_seen": "2026-10-01 08:00:00",
                "last_seen": "2026-10-10 17:00:00",
            },
            {
                "mac": "AA:BB:CC:DD:EE:02",
                "hostname": "unknown-phone",
                "ip": "192.168.1.55",
                "status": "unknown",
                "vendor": "Apple",
                "first_seen": "2026-10-10 16:30:00",
                "last_seen": "2026-10-10 17:00:00",
            },
        ]

    def list_events(self, limit: int) -> list[dict]:
        return [
            {"at": "2026-10-10 17:00:00", "message": "فحص دوري مكتمل"},
            {"at": "2026-10-10 16:30:00", "message": "جهاز جديد غريب: AA:BB:CC:DD:EE:02"},
        ][:limit]

    def speed_history(self, hours: int) -> list[dict]:
        return [
            {"at": "2026-10-10 16:00:00", "down_mbps": 45.2, "up_mbps": 10.1, "ping_ms": 18},
            {"at": "2026-10-10 17:00:00", "down_mbps": 47.8, "up_mbps": 9.6, "ping_ms": 21},
        ]

    def list_outages(self, hours: int) -> list[dict]:
        return [
            {
                "started_at": "2026-10-10 03:12:00",
                "ended_at": "2026-10-10 03:15:30",
                "duration_sec": 210,
            }
        ]

    def run_scan(self) -> dict:
        return {"ok": True, "message": "اكتمل الفحص: جهازان متصلان"}

    def block_device(self, mac: str) -> dict:
        return {"ok": True, "message": f"تم حظر {mac}"}

    def acknowledge_all(self) -> dict:
        return {"ok": True, "message": "تم إقرار كل التنبيهات"}

    def daily_report(self) -> dict:
        return {"date": "2026-10-10", "summary": "تقرير وهمي للاختبار"}


class BrokenController(FakeController):
    """controller يرمي استثناءً دائماً — لاختبار مسار الخطأ 500."""

    def get_status(self) -> dict:  # type: ignore[override]
        raise RuntimeError("عطل وهمي")


@pytest.fixture()
def client():
    """test client مبني فوق FakeController."""
    app: Flask = create_app(FakeController())
    app.testing = True
    return app.test_client()


@pytest.fixture()
def broken_client():
    """test client مبني فوق controller معطوب."""
    app: Flask = create_app(BrokenController())
    app.testing = True
    return app.test_client()


def test_index_returns_200_with_brand(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "RouterGuard" in resp.get_data(as_text=True)


def test_api_status_ok(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["router_ok"] is True


def test_api_devices_ok(client):
    resp = client.get("/api/devices")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert len(body["data"]) == 2


def test_api_events_ok(client):
    resp = client.get("/api/events?limit=50")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert len(body["data"]) == 2


def test_api_speed_ok(client):
    resp = client.get("/api/speed?hours=24")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"][0]["down_mbps"] == 45.2


def test_api_outages_ok(client):
    resp = client.get("/api/outages?hours=24")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"][0]["duration_sec"] == 210


def test_api_report_ok(client):
    resp = client.get("/api/report")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["date"] == "2026-10-10"


def test_api_scan_ok(client):
    resp = client.post("/api/scan")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "message" in body


def test_api_block_without_mac_returns_400(client):
    resp = client.post("/api/block", json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False


def test_api_block_with_mac_ok(client):
    resp = client.post("/api/block", json={"mac": "AA:BB:CC:DD:EE:02"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True


def test_api_ack_ok(client):
    resp = client.post("/api/ack")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_controller_exception_becomes_500(broken_client):
    resp = broken_client.get("/api/status")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    assert "message" in body


# ---------- اختبارات التصميم الجديد (Claude-style) ----------

def test_index_has_theme_toggle_and_persistence(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="themeToggle"' in html
    assert "rg-theme" in html
    assert "localStorage" in html
    assert 'data-theme' in html


def test_index_uses_cairo_font(client):
    html = client.get("/").get_data(as_text=True)
    assert "Cairo" in html
    assert "fonts.googleapis.com" in html


def test_index_has_kashida_headings(client):
    """المد (ـ) في العناوين الرئيسية فقط وبشكل صحيح."""
    html = client.get("/").get_data(as_text=True)
    assert "لوحــة التحكــم" in html
    assert "الأجهــزة" in html
    assert "سجــل الأحــداث" in html
    # ممنوع المد في بداية الكلمة
    assert "الــــسلام" not in html


def test_index_has_live_clock_and_relative_scan(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="clock"' in html
    assert 'id="cardLastScan"' in html
    assert "relTime" in html


def test_index_shows_device_presence_column(client):
    html = client.get("/").get_data(as_text=True)
    assert "التواجد" in html
    assert "presenceBadge" in html
    assert "متصل الآن" in html
