"""تنبيه عبر البريد الإلكتروني (SMTP) مع دعم العربية."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .base import Alert, AlertPlugin


class EmailAlert(AlertPlugin):
    """يرسل التنبيه بريدياً عبر smtplib مع EmailMessage (يدعم UTF-8)."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        use_tls: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls
        self._logger = logger or logging.getLogger("routerguard.alerts")

    @property
    def name(self) -> str:
        return "email"

    def send(self, alert: Alert) -> bool:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[RouterGuard][{alert.severity}] {alert.title}"
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)
            body = f"{alert.title}\n\n{alert.message}\n\nالوقت: {alert.at:%Y-%m-%d %H:%M}"
            if alert.mac:
                body += f"\nMAC: {alert.mac}"
            msg.set_content(body)  # EmailMessage يدعم UTF-8 افتراضياً
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)
            return True
        except Exception:  # noqa: BLE001
            self._logger.exception("فشل إرسال تنبيه البريد الإلكتروني")
            return False
