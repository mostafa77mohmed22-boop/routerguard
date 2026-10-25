"""اختبارات حزمة التنبيهات (مع mocks — لا شبكة حقيقية)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

from alerts.base import Alert, AlertManager, AlertPlugin
from alerts.escalation import EscalationService
from alerts.telegram import TelegramAlert
from alerts.webhook import WebhookAlert


@pytest.fixture
def logger():
    return logging.getLogger("test")


@pytest.fixture
def alert():
    return Alert(
        title="جهاز دخيل", message="تم رصد جهاز غير معروف",
        severity="critical", mac="AA:BB:CC:DD:EE:FF",
    )


class OkPlugin(AlertPlugin):
    @property
    def name(self):
        return "ok"

    def send(self, alert):
        return True


class FailPlugin(AlertPlugin):
    @property
    def name(self):
        return "fail"

    def send(self, alert):
        raise RuntimeError("boom")


class FalsePlugin(AlertPlugin):
    @property
    def name(self):
        return "false"

    def send(self, alert):
        return False


def test_fanout_survives_failing_plugin(logger, alert):
    """plugin يفشل باستثناء: يجب ألا يسقط بقية الإضافات."""
    mgr = AlertManager(logger=logger)
    mgr.register(OkPlugin())
    mgr.register(FailPlugin())
    mgr.register(FalsePlugin())
    results = mgr.notify(alert)
    assert results == {"ok": True, "fail": False, "false": False}


def test_telegram_send_mocked(logger, alert, monkeypatch):
    """إرسال تيليغرام مع requests.post مُموّهة."""
    posted = {}

    class Resp:
        def json(self):
            return {"ok": True}

    def fake_post(url, json=None, timeout=None):
        posted["url"] = url
        posted["json"] = json
        return Resp()

    monkeypatch.setattr("alerts.telegram.requests.post", fake_post)
    plugin = TelegramAlert("TOKEN123", "999", logger=logger)
    assert plugin.send(alert) is True
    assert posted["url"] == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert "جهاز دخيل" in posted["json"]["text"]
    assert posted["json"]["parse_mode"] == "HTML"


def test_telegram_send_not_ok(logger, alert, monkeypatch):
    class Resp:
        def json(self):
            return {"ok": False, "description": "bad"}

    monkeypatch.setattr(
        "alerts.telegram.requests.post", lambda *a, **k: Resp()
    )
    assert TelegramAlert("T", "1", logger=logger).send(alert) is False


def test_webhook_mocked(logger, alert, monkeypatch):
    posted = {}

    class Resp:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, headers=None, timeout=None):
        posted["payload"] = json
        return Resp()

    monkeypatch.setattr("alerts.webhook.requests.post", fake_post)
    plugin = WebhookAlert("https://example.com/hook", logger=logger)
    assert plugin.send(alert) is True
    assert posted["payload"]["title"] == "جهاز دخيل"
    assert posted["payload"]["severity"] == "critical"
    assert posted["payload"]["mac"] == "AA:BB:CC:DD:EE:FF"


def test_escalation_raise_tick_acknowledge(logger, alert):
    mgr = AlertManager(logger=logger)
    received = []

    class Spy(AlertPlugin):
        @property
        def name(self):
            return "spy"

        def send(self, a):
            received.append(a)
            return True

    mgr.register(Spy())
    esc = EscalationService(mgr, repeat_minutes=5, max_repeats=3, logger=logger)

    esc_id = esc.raise_critical(alert)
    assert received  # إرسال فوري
    assert len(esc.pending_list()) == 1

    # tick قبل الاستحقاق: لا إعادة إرسال
    assert esc.tick(datetime.now()) == []
    assert len(received) == 1

    # tick بعد الاستحقاق: إعادة إرسال
    due = esc.tick(datetime.now() + timedelta(minutes=6))
    assert due == [esc_id]
    assert len(received) == 2

    # الإقرار يوقف التكرار
    assert esc.acknowledge(esc_id) is True
    assert esc.pending_list() == []
    assert esc.tick(datetime.now() + timedelta(minutes=60)) == []
    assert len(received) == 2
    assert esc.acknowledge("غير-موجود") is False
