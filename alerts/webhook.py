"""تنبيه عبر Webhook: POST بملف JSON."""
from __future__ import annotations

import logging

import requests

from .base import Alert, AlertPlugin


class WebhookAlert(AlertPlugin):
    """يرسل JSON بالتنبيه إلى URL خارجي."""

    def __init__(
        self,
        url: str,
        headers: dict | None = None,
        timeout: int = 10,
        logger: logging.Logger | None = None,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self._timeout = timeout
        self._logger = logger or logging.getLogger("routerguard.alerts")

    @property
    def name(self) -> str:
        return "webhook"

    def send(self, alert: Alert) -> bool:
        payload = {
            "title": alert.title,
            "message": alert.message,
            "severity": alert.severity,
            "mac": alert.mac,
            "at": alert.at.isoformat(),
        }
        try:
            resp = requests.post(
                self.url, json=payload, headers=self.headers, timeout=self._timeout
            )
            resp.raise_for_status()
            return True
        except Exception:  # noqa: BLE001
            self._logger.exception("فشل إرسال webhook إلى %s", self.url)
            return False
