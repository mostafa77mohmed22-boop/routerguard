"""تنبيهات تيليغرام: إرسال + بوت أوامر تفاعلي (long-polling)."""
from __future__ import annotations

import html
import logging
import threading
import time
from collections.abc import Callable

import requests

from .base import Alert, AlertPlugin

_SEVERITY_ICON = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}


class TelegramAlert(AlertPlugin):
    """يرسل التنبيه عبر Bot API بنص HTML."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        logger: logging.Logger | None = None,
        timeout: int = 10,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._timeout = timeout
        self._logger = logger or logging.getLogger("routerguard.alerts")

    @property
    def name(self) -> str:
        return "telegram"

    def _format(self, alert: Alert) -> str:
        icon = _SEVERITY_ICON.get(alert.severity, "ℹ️")
        lines = [
            f"{icon} <b>{html.escape(alert.title)}</b>",
            html.escape(alert.message),
        ]
        if alert.mac:
            lines.append(f"MAC: <code>{html.escape(alert.mac)}</code>")
        lines.append(alert.at.strftime("%Y-%m-%d %H:%M"))
        return "\n".join(lines)

    def send(self, alert: Alert) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": self._format(alert),
                    "parse_mode": "HTML",
                },
                timeout=self._timeout,
            )
            data = resp.json()
            if data.get("ok"):
                return True
            self._logger.warning("Telegram رفض الإرسال: %s", data)
            return False
        except Exception:  # noqa: BLE001
            self._logger.exception("فشل إرسال تنبيه تيليغرام")
            return False


class TelegramCommandBot:
    """بوت أوامر يعمل في thread خلفي عبر long-polling على getUpdates.

    يستجيب فقط لرسائل chat_id المطابق. الأوامر المدعومة:
    /start /help /status /scan /devices /block <mac> /events
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        callbacks: dict[str, Callable[[list[str]], str]],
        logger: logging.Logger | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self._callbacks = callbacks
        self._logger = logger or logging.getLogger("routerguard.alerts")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """بدء حلقة الـ long-poll في thread خلفي (daemon)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="telegram-bot", daemon=True
        )
        self._thread.start()
        self._logger.info("بوت تيليغرام بدأ")

    def stop(self) -> None:
        """إيقاف حلقة الـ long-poll."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=35)
        self._logger.info("بوت تيليغرام توقف")

    # ---- الحلقة الداخلية ----

    def _poll_loop(self) -> None:
        base = f"https://api.telegram.org/bot{self.bot_token}"
        offset = 0
        while not self._stop.is_set():
            try:
                resp = requests.get(
                    f"{base}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                    timeout=35,
                )
                updates = resp.json().get("result", [])
            except Exception:  # noqa: BLE001
                self._logger.debug("getUpdates فشل، إعادة المحاولة", exc_info=True)
                time.sleep(5)
                continue
            for update in updates:
                offset = max(offset, update.get("update_id", 0) + 1)
                self._handle_update(update)

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        if str(chat.get("id", "")) != self.chat_id:
            return  # تجاهل الرسائل من غير المالك
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        command = parts[0][1:].split("@")[0]  # إزالة البادئة واسم البوت
        args = parts[1:]
        reply = self._dispatch(command, args)
        self._reply(msg.get("chat", {}).get("id"), reply)

    def _dispatch(self, command: str, args: list[str]) -> str:
        if command in ("start", "help"):
            return (
                "🤖 RouterGuard\n"
                "/status — حالة الراوتر\n"
                "/scan — فحص الآن\n"
                "/devices — قائمة الأجهزة\n"
                "/block <mac> — حظر جهاز\n"
                "/events — آخر الأحداث"
            )
        handler = self._callbacks.get(command)
        if handler is None:
            return "❓ أمر غير معروف. جرّب /help"
        try:
            return handler(args)
        except Exception:  # noqa: BLE001
            self._logger.exception("فشل تنفيذ الأمر /%s", command)
            return "⚠️ حدث خطأ أثناء تنفيذ الأمر"

    def _reply(self, chat_id: str | int | None, text: str) -> None:
        if not chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            self._logger.exception("فشل الرد على رسالة تيليغرام")
