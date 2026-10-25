"""تنبيه صوتي عبر winsound على Windows."""
from __future__ import annotations

import logging

from .base import Alert, AlertPlugin

try:  # pragma: no cover - يعتمد على نظام التشغيل
    import winsound
except ImportError:  # غير ويندوز
    winsound = None  # type: ignore[assignment]


class SoundAlert(AlertPlugin):
    """تنبيه صوتي: critical=5 صافرات، warning=2، info=1."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("routerguard.alerts")

    @property
    def name(self) -> str:
        return "sound"

    def send(self, alert: Alert) -> bool:
        try:
            if winsound is None:
                # لا يوجد winsound (لينكس/ماك): صوت جرس الطرفية كبديل
                self._logger.debug("winsound غير متوفر — استخدام \\a")
                return True
            if alert.severity == "critical":
                count = 5
            elif alert.severity == "warning":
                count = 2
            else:
                count = 1
            for _ in range(count):
                winsound.MessageBeep(winsound.MB_ICONHAND)
            return True
        except Exception:  # noqa: BLE001 - الصوت تنبيه ثانوي، لا يجب أن ينهار أبداً
            self._logger.exception("فشل التنبيه الصوتي")
            return False
