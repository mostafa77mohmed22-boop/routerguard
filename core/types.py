"""الأنواع المشتركة بين مكونات RouterGuard."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DeviceRow:
    """صف جهاز واحد كما يُقرأ من جدول DHCP في الراوتر."""
    hostname: str = ""
    ip: str = ""
    mac: str = ""
    raw: str = ""  # النص الخام للصف كما ظهر في الجدول

    def normalized_mac(self) -> str:
        """MAC بصيغة موحدة AA:BB:CC:DD:EE:FF."""
        cleaned = "".join(c for c in self.mac.upper() if c in "0123456789ABCDEF")
        if len(cleaned) != 12:
            return self.mac.upper().strip()
        return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


@dataclass
class ScanOutcome:
    """نتيجة فحص واحد كامل."""
    at: datetime = field(default_factory=datetime.now)
    devices: list[DeviceRow] = field(default_factory=list)
    intruders: list[DeviceRow] = field(default_factory=list)
    new_devices: list[DeviceRow] = field(default_factory=list)
    ok: bool = True
    error: str = ""
