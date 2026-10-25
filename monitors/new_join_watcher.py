"""مراقب الانضمام الفوري: تنبيه لحظي عند ظهور جهاز جديد."""
from __future__ import annotations

import logging
from typing import Callable

from alerts.base import Alert
from core.types import DeviceRow
from monitors.device_monitor import BLOCKED, UNKNOWN

log = logging.getLogger("routerguard.newjoin")


class NewJoinWatcher:
    """يرسل تنبيهاً فورياً لكل جهاز يظهر لأول مرة."""

    def __init__(self, notify: Callable[[Alert], None],
                 oui_lookup: Callable[[str], str | None] | None = None):
        self.notify = notify
        self.oui_lookup = oui_lookup or (lambda mac: None)

    def watch(self, new_devices: list[DeviceRow],
              statuses: dict[str, str]) -> None:
        """new_devices من DeviceMonitor.evaluate، وstatuses: mac -> status."""
        for row in new_devices:
            mac = row.normalized_mac()
            status = statuses.get(mac, UNKNOWN)
            vendor = self.oui_lookup(mac)
            severity = "critical" if status == BLOCKED else "warning"
            title = ("جهاز محظور انضم للشبكة!" if status == BLOCKED
                     else "جهاز جديد انضم للشبكة")
            lines = [
                f"الاسم: {row.hostname or 'بدون اسم'}",
                f"MAC: {mac}",
                f"IP: {row.ip or 'غير معروف'}",
            ]
            if vendor:
                lines.append(f"الشركة المصنعة: {vendor}")
            self.notify(Alert(title=title, message="\n".join(lines),
                              severity=severity, mac=mac))
            log.info("تنبيه انضمام جديد: %s (%s)", row.hostname, mac)
