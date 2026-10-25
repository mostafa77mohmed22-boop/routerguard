"""حزمة التنبيهات: إضافات plugin عبر AlertManager."""

from .base import Alert, AlertManager, AlertPlugin
from .desktop import DesktopAlert
from .email import EmailAlert
from .escalation import EscalationService
from .sound import SoundAlert
from .telegram import TelegramAlert, TelegramCommandBot
from .webhook import WebhookAlert

__all__ = [
    "Alert",
    "AlertManager",
    "AlertPlugin",
    "DesktopAlert",
    "EmailAlert",
    "EscalationService",
    "SoundAlert",
    "TelegramAlert",
    "TelegramCommandBot",
    "WebhookAlert",
    "build_alert_manager",
]


def build_alert_manager(
    cfg: dict, logger
) -> tuple[AlertManager, EscalationService | None]:
    """يبني AlertManager من قسم cfg["alerts"] مع الإضافات المفعّلة.

    القيم الحساسة (tokens/كلمات المرور) تأتي محلولة مسبقاً من الـ config loader —
    هذه الدالة لا تقرأ متغيرات البيئة.
    """
    alerts_cfg = (cfg or {}).get("alerts") or {}
    manager = AlertManager(logger=logger)

    if alerts_cfg.get("sound"):
        manager.register(SoundAlert(logger=logger))
    if alerts_cfg.get("desktop"):
        manager.register(DesktopAlert(logger=logger))

    tg = alerts_cfg.get("telegram") or {}
    if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
        manager.register(
            TelegramAlert(
                bot_token=tg["bot_token"],
                chat_id=str(tg["chat_id"]),
                logger=logger,
            )
        )
    elif tg.get("enabled"):
        logger.warning("تيليغرام مفعّل لكن bot_token أو chat_id مفقود")

    em = alerts_cfg.get("email") or {}
    if em.get("enabled") and em.get("smtp_host") and em.get("to_addrs"):
        manager.register(
            EmailAlert(
                smtp_host=em["smtp_host"],
                smtp_port=int(em.get("smtp_port", 587)),
                username=em.get("username") or "",
                password=em.get("password") or "",
                from_addr=em.get("from_addr") or em.get("username") or "",
                to_addrs=list(em["to_addrs"]),
                use_tls=bool(em.get("use_tls", True)),
                logger=logger,
            )
        )
    elif em.get("enabled"):
        logger.warning("البريد مفعّل لكن الإعدادات ناقصة")

    wh = alerts_cfg.get("webhook") or {}
    if wh.get("enabled") and wh.get("url"):
        manager.register(
            WebhookAlert(
                url=wh["url"],
                headers=wh.get("headers"),
                timeout=int(wh.get("timeout", 10)),
                logger=logger,
            )
        )
    elif wh.get("enabled"):
        logger.warning("webhook مفعّل لكن url مفقود")

    escalation = None
    esc = alerts_cfg.get("escalation") or {}
    if esc.get("enabled"):
        escalation = EscalationService(
            manager,
            repeat_minutes=int(esc.get("repeat_minutes", 5)),
            max_repeats=int(esc.get("max_repeats", 6)),
            logger=logger,
        )

    return manager, escalation
