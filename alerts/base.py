"""أنواع التنبيهات الأساسية: Alert و AlertPlugin و AlertManager."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Alert:
    """تنبيه واحد يرسله RouterGuard."""

    title: str
    message: str
    severity: str  # "info" | "warning" | "critical"
    mac: str | None = None
    extra: dict | None = None
    at: datetime = field(default_factory=datetime.now)


class AlertPlugin(ABC):
    """واجهة أي إضافة تنبيه (صوت، سطح مكتب، تيليغرام، ...)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """اسم فريد للإضافة."""
        ...

    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """إرسال التنبيه. يعيد True عند النجاح."""
        ...


class AlertManager:
    """يوزّع التنبيهات على كل الإضافات المسجلة (fan-out).

    أي إضافة تفشل أو ترفع استثناء تُسجَّل في الـ logger ولا تسقط بقية الإضافات.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("routerguard.alerts")
        self._plugins: list[AlertPlugin] = []

    def register(self, plugin: AlertPlugin) -> None:
        """تسجيل إضافة تنبيه جديدة."""
        self._plugins.append(plugin)
        self._logger.debug("تم تسجيل إضافة التنبيه: %s", plugin.name)

    def notify(self, alert: Alert) -> dict[str, bool]:
        """إرسال التنبيه لكل الإضافات. يعيد dict بالاسم -> نتيجة الإرسال."""
        results: dict[str, bool] = {}
        for plugin in self._plugins:
            try:
                ok = bool(plugin.send(alert))
            except Exception:  # noqa: BLE001 - يجب ألا تسقط إضافة باقي الإضافات
                self._logger.exception(
                    "إضافة التنبيه '%s' فشلت في إرسال التنبيه", plugin.name
                )
                ok = False
            else:
                if not ok:
                    self._logger.warning(
                        "إضافة التنبيه '%s' أعادت False", plugin.name
                    )
            results[plugin.name] = ok
        return results
