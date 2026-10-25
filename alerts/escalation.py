"""خدمة التصعيد: إعادة إرسال التنبيهات الحرجة دورياً حتى الإقرار بها."""
from __future__ import annotations

import itertools
import logging
import threading
from datetime import datetime, timedelta

from .base import Alert, AlertManager


class EscalationService:
    """تُعيد إرسال التنبيهات الحرجة كل repeat_minutes حتى max_repeats أو الإقرار.

    آمنة للـ threads (Lock). استخدم `tick()` من حلقة دورية في الخيط الرئيسي.
    """

    def __init__(
        self,
        manager: AlertManager,
        repeat_minutes: int = 5,
        max_repeats: int = 6,
        logger: logging.Logger | None = None,
    ) -> None:
        self._manager = manager
        self._repeat = timedelta(minutes=repeat_minutes)
        self._max_repeats = max_repeats
        self._logger = logger or logging.getLogger("routerguard.alerts")
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        # esc_id -> {"alert": Alert, "sent": int, "next_at": datetime}
        self._pending: dict[str, dict] = {}

    def raise_critical(self, alert: Alert) -> str:
        """تسجيل تنبيه حرج للتصعيد وإرساله فوراً. يعيد معرّف التصعيد."""
        esc_id = f"esc-{next(self._counter)}"
        with self._lock:
            self._pending[esc_id] = {
                "alert": alert,
                "sent": 1,
                "next_at": datetime.now() + self._repeat,
            }
        self._logger.warning(
            "تصعيد جديد %s: %s (التنبيه الحرج %d)", esc_id, alert.title, 1
        )
        self._manager.notify(alert)
        return esc_id

    def tick(self, now: datetime | None = None) -> list[str]:
        """إعادة إرسال التصعيدات المستحقة. يعيد قائمة المعرّفات التي أُعيد إرسالها."""
        now = now or datetime.now()
        due: list[str] = []
        with self._lock:
            for esc_id, item in list(self._pending.items()):
                if item["next_at"] <= now and item["sent"] < self._max_repeats:
                    due.append(esc_id)
                    item["sent"] += 1
                    item["next_at"] = now + self._repeat
                elif item["sent"] >= self._max_repeats:
                    del self._pending[esc_id]
                    self._logger.warning(
                        "انتهت محاولات التصعيد %s دون إقرار", esc_id
                    )
        for esc_id in due:
            with self._lock:
                alert = self._pending[esc_id]["alert"]
            self._logger.warning("إعادة إرسال التصعيد %s", esc_id)
            self._manager.notify(alert)
        return due

    def acknowledge(self, esc_id: str) -> bool:
        """الإقرار بالتصعيد وإيقاف تكراره. يعيد True إن كان موجوداً."""
        with self._lock:
            removed = self._pending.pop(esc_id, None)
        if removed is not None:
            self._logger.info("تم الإقرار بالتصعيد %s", esc_id)
            return True
        return False

    def pending_list(self) -> list[dict]:
        """قائمة التصعيدات النشطة."""
        with self._lock:
            return [
                {
                    "id": esc_id,
                    "title": item["alert"].title,
                    "severity": item["alert"].severity,
                    "sent": item["sent"],
                    "next_at": item["next_at"].isoformat(),
                }
                for esc_id, item in self._pending.items()
            ]
