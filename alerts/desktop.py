"""تنبيه سطح المكتب: plyer أولاً، ثم PowerShell toast على Windows كخطة بديلة."""
from __future__ import annotations

import logging
import platform
import subprocess

from .base import Alert, AlertPlugin


class DesktopAlert(AlertPlugin):
    """إشعار سطح مكتب بعنوان RouterGuard."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("routerguard.alerts")

    @property
    def name(self) -> str:
        return "desktop"

    def send(self, alert: Alert) -> bool:
        if self._try_plyer(alert):
            return True
        if platform.system() == "Windows" and self._try_powershell_toast(alert):
            return True
        self._logger.warning(
            "تعذّر عرض إشعار سطح المكتب (plyer وPowerShell غير متاحين)"
        )
        return False

    def _try_plyer(self, alert: Alert) -> bool:
        try:
            from plyer import notification

            notification.notify(
                title="RouterGuard",
                message=f"{alert.title}\n{alert.message}",
                app_name="RouterGuard",
                timeout=10,
            )
            return True
        except Exception:  # noqa: BLE001
            self._logger.debug("plyer غير متاح أو فشل", exc_info=True)
            return False

    def _try_powershell_toast(self, alert: Alert) -> bool:
        try:
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, "
                "Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                "$tpl = [Windows.UI.Notifications.ToastTemplateType]::ToastText02;"
                "$xml = [Windows.UI.Notifications.ToastNotificationManager]::"
                "GetTemplateContent($tpl);"
                "$xml.GetElementsByTagName('text')[0].AppendChild("
                "$xml.CreateTextNode($args[0])) > $null;"
                "$xml.GetElementsByTagName('text')[1].AppendChild("
                "$xml.CreateTextNode($args[1])) > $null;"
                "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml;"
                "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::"
                "CreateToastNotifier('RouterGuard');"
                "$notifier.Show($toast)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps, alert.title, alert.message],
                check=True,
                timeout=15,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:  # noqa: BLE001
            self._logger.debug("PowerShell toast فشل", exc_info=True)
            return False
