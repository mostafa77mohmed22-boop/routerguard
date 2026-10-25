"""مراقب الأجهزة: تصنيف، تتبع الظهور، وكشف انتحال MAC."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.types import DeviceRow

log = logging.getLogger("routerguard.devices")

# حالات الجهاز
ALLOWED = "allowed"    # مسموح
VISITOR = "visitor"    # زائر معروف
UNKNOWN = "unknown"    # غريب
BLOCKED = "blocked"    # محظور (قائمة سوداء)

STATUS_AR = {
    ALLOWED: "مسموح",
    VISITOR: "زائر",
    UNKNOWN: "غريب",
    BLOCKED: "محظور",
}


class DeviceMonitor:
    """يقارن أجهزة الفحص الحالي بالقوائم ويصنّفها."""

    def __init__(self, db, cfg: dict, oui_lookup: Optional[Callable[[str], Optional[str]]] = None,
                 data_dir: str | Path = "data"):
        self.db = db
        dev = cfg.get("devices", {})
        self.allowed_names = [str(n).lower() for n in dev.get("allowed", [])]
        self.allowed_macs = {self._norm(m) for m in dev.get("allowed_macs", []) if m}
        self.visitor_names = [str(n).lower() for n in dev.get("visitors", [])]
        self.visitor_macs = {self._norm(m) for m in dev.get("visitors_macs", []) if m}
        self.blacklist_names = [str(n).lower() for n in dev.get("blacklist", [])]
        self.blacklist_macs = {self._norm(m) for m in dev.get("blacklist_macs", []) if m}
        self.oui_lookup = oui_lookup or (lambda mac: None)
        # قائمة حظر ديناميكية يديرها التطبيق (أمر block / زر الحظر)
        self.data_dir = Path(data_dir)
        self.blocklist_path = self.data_dir / "blocklist.json"
        self.blocklist_macs = self._load_blocklist()

    @staticmethod
    def _norm(mac: str) -> str:
        cleaned = "".join(c for c in mac.upper() if c in "0123456789ABCDEF")
        if len(cleaned) == 12:
            return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))
        return mac.upper()

    def classify(self, row: DeviceRow) -> str:
        """يصنف جهازاً واحداً: blocked / allowed / visitor / unknown."""
        mac = row.normalized_mac()
        name = (row.hostname or "").lower()

        if mac in self.blacklist_macs or mac in self.blocklist_macs \
                or any(b in name for b in self.blacklist_names if b):
            return BLOCKED
        if mac in self.allowed_macs or any(a in name for a in self.allowed_names if a):
            return ALLOWED
        if mac in self.visitor_macs or any(v in name for v in self.visitor_names if v):
            return VISITOR
        return UNKNOWN

    def _check_spoof(self, row: DeviceRow, known_by_name: dict[str, dict]) -> Optional[str]:
        """يكشف ظهور نفس الاسم بعنوان MAC مختلف (انتحال محتمل)."""
        known = known_by_name.get((row.hostname or "").lower())
        if not known or not row.hostname:
            return None
        mac = row.normalized_mac()
        old_mac = (known.get("mac") or "").upper()
        if old_mac and old_mac != mac:
            return (
                f"انتحال MAC محتمل: الجهاز '{row.hostname}' ظهر بعنوان "
                f"مختلف ({old_mac} <- {mac})"
            )
        return None

    # ---------- قائمة الحظر الديناميكية ----------

    def _load_blocklist(self) -> set[str]:
        try:
            if self.blocklist_path.exists():
                data = json.loads(self.blocklist_path.read_text(encoding="utf-8"))
                return {self._norm(m) for m in data if m}
        except Exception as exc:
            log.error("تعذر قراءة blocklist.json: %s", exc)
        return set()

    def _save_blocklist(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.blocklist_path.write_text(
            json.dumps(sorted(self.blocklist_macs), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def block_mac(self, mac: str) -> bool:
        """يضيف MAC لقائمة الحظر. يعيد True إن كان جديداً."""
        mac = self._norm(mac)
        if not mac or len(mac.replace(":", "")) != 12:
            return False
        if mac in self.blocklist_macs:
            return False
        self.blocklist_macs.add(mac)
        self._save_blocklist()
        try:
            self.db.update_device_status(mac, BLOCKED)
        except Exception:
            pass
        log.info("تم حظر MAC: %s", mac)
        return True

    def unblock_mac(self, mac: str) -> bool:
        mac = self._norm(mac)
        if mac not in self.blocklist_macs:
            return False
        self.blocklist_macs.discard(mac)
        self._save_blocklist()
        log.info("تم إلغاء حظر MAC: %s", mac)
        return True

    def evaluate(self, rows: list[DeviceRow], at: Optional[datetime] = None):
        """يقيّم الفحص: يحدّث قاعدة البيانات ويعيد القوائم المهمة.

        يعيد: (intruders, new_devices, spoof_warnings)
        """
        at = at or datetime.now()
        intruders: list[DeviceRow] = []
        new_devices: list[DeviceRow] = []
        spoof_warnings: list[str] = []

        # خريطة الأسماء المعروفة لكشف انتحال MAC (اسم واحد -> MAC مختلف)
        known_by_name: dict[str, dict] = {}
        try:
            for d in self.db.list_devices():
                if d.get("hostname"):
                    known_by_name[d["hostname"].lower()] = d
        except Exception as exc:
            log.debug("تعذر جلب الأجهزة المعروفة: %s", exc)

        for row in rows:
            mac = row.normalized_mac()
            if not mac:
                log.warning("صف بلا MAC صالح تم تجاهله: %s", row.raw[:60])
                continue

            status = self.classify(row)

            spoof = self._check_spoof(row, known_by_name)
            if spoof:
                spoof_warnings.append(spoof)
                self.db.record_event("spoof", "critical", spoof, mac=mac)

            vendor = self.oui_lookup(mac)
            _id, is_new = self.db.upsert_device(mac, row.hostname, row.ip, status)
            if vendor:
                # حفظ الشركة المصنعة عند توفرها
                try:
                    self.db.set_vendor(mac, vendor)
                except AttributeError:
                    pass
            self.db.touch_seen(mac, at)

            if is_new:
                new_devices.append(row)
                self.db.record_event(
                    "new_device",
                    "warning" if status in (UNKNOWN, BLOCKED) else "info",
                    f"جهاز جديد انضم: {row.hostname or 'بدون اسم'} ({mac})",
                    mac=mac,
                )

            if status in (UNKNOWN, BLOCKED):
                intruders.append(row)
                self.db.record_event(
                    "intruder",
                    "critical" if status == BLOCKED else "warning",
                    f"جهاز {('محظور' if status == BLOCKED else 'غريب')}: "
                    f"{row.hostname or 'بدون اسم'} ({mac})",
                    mac=mac,
                )

        # كشف الأجهزة التي غادرت: كانت حاضرة واختفت من الفحص الحالي
        # (يُستدعى evaluate فقط عند نجاح الفحص، فلا إنذارات كاذبة عند فشله)
        seen_macs = {r.normalized_mac() for r in rows if r.normalized_mac()}
        try:
            known_devices = self.db.list_devices()
        except Exception as exc:
            log.debug("تعذر جلب الأجهزة لكشف المغادرة: %s", exc)
            known_devices = []
        for d in known_devices:
            mac = d.get("mac")
            if d.get("present", 1) == 1 and mac and mac not in seen_macs:
                try:
                    self.db.mark_device_left(mac, at)
                except AttributeError:
                    pass  # قاعدة بيانات قديمة بدون دعم present
                name = d.get("hostname") or "بدون اسم"
                self.db.record_event(
                    "device_left",
                    "info",
                    f"الجهاز غادر الشبكة: {name} ({mac})",
                    mac=mac,
                )
                log.info("جهاز غادر الشبكة: %s (%s)", name, mac)

        return intruders, new_devices, spoof_warnings
