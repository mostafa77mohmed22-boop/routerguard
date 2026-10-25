"""البحث عن الشركة المصنّعة من عنوان MAC (OUI) — يعمل offline تماماً."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("routerguard.oui")

# قاموس OUI مدمج: أول 3 بايتات من MAC -> الشركة
OUI_DB: dict[str, str] = {
    "3C:22:FB": "Apple",
    "8C:85:90": "Apple",
    "AC:BC:32": "Apple",
    "F0:18:98": "Apple",
    "78:CA:39": "Apple",
    "8C:7B:9D": "Apple",
    "40:A3:CC": "Apple",
    "7C:C3:A1": "Apple",
    "24:A2:E1": "Samsung",
    "00:1B:9E": "Samsung",
    "E4:7D:BD": "Samsung",
    "8C:F5:A3": "Samsung",
    "50:CC:F8": "Samsung",
    "64:B3:10": "Xiaomi",
    "7C:2F:80": "Xiaomi",
    "98:0C:82": "Xiaomi",
    "C4:0B:CB": "Xiaomi",
    "0C:1D:AF": "Xiaomi",
    "0C:8C:DC": "Huawei",
    "48:46:FB": "Huawei",
    "E8:CD:2D": "Huawei",
    "B4:15:13": "Huawei",
    "50:2B:73": "TP-Link",
    "14:CC:20": "TP-Link",
    "D8:0D:17": "TP-Link",
    "A8:42:A1": "TP-Link",
    "70:4F:57": "TP-Link",
    "00:1E:C9": "Intel",
    "7C:7A:91": "Intel",
    "90:61:AE": "Intel",
    "A4:02:B9": "Intel",
    "94:E9:79": "Qualcomm",
    "F4:F5:D8": "Qualcomm",
    "00:A0:C6": "Qualcomm",
    "00:E0:4C": "Realtek",
    "52:54:00": "Realtek",
    "00:0C:E7": "MediaTek",
    "3C:CD:57": "MediaTek",
    "24:6F:28": "Espressif",
    "24:0A:C4": "Espressif",
    "30:AE:A4": "Espressif",
    "DC:4F:22": "Espressif",
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "F0:EF:86": "Google",
    "3C:28:6D": "Google",
    "54:60:09": "Google",
    "F4:F5:E8": "Google",
    "0C:47:C9": "Amazon",
    "FC:A1:83": "Amazon",
    "74:C2:46": "Amazon",
    "40:B4:CD": "Amazon",
    "7C:1E:52": "Microsoft",
    "00:15:5D": "Microsoft",
    "28:18:78": "Microsoft",
    "FC:3F:DB": "Sony",
    "00:1E:D5": "Sony",
    "AC:9B:0A": "Sony",
    "9C:30:5B": "LG",
    "A8:23:FE": "LG",
    "00:1C:B3": "LG",
    "F8:BC:12": "Dell",
    "D4:BE:D9": "Dell",
    "18:DB:F2": "Dell",
    "74:86:7A": "Dell",
    "A4:1F:72": "HP",
    "3C:D9:2B": "HP",
    "9C:8E:CD": "HP",
    "8C:DC:D4": "HP",
    "54:EE:75": "Lenovo",
    "8C:16:45": "Lenovo",
    "E8:D3:EB": "Lenovo",
    "2C:33:7A": "Asus",
    "04:D9:F5": "Asus",
    "1C:87:2C": "Asus",
    "00:1E:13": "Cisco",
    "00:1C:0E": "Cisco",
    "58:6D:8F": "Cisco",
    "2C:3E:CF": "Netgear",
    "44:94:FC": "Netgear",
    "9C:C7:A6": "Netgear",
    "C8:3A:35": "Tenda",
    "D8:32:14": "Tenda",
    "00:B0:0C": "Tenda",
    "00:19:C6": "ZTE",
    "CC:53:A8": "ZTE",
    "34:6F:92": "ZTE",
    "00:1D:D9": "Nokia",
    "24:DA:9B": "Nokia",
    "F4:4E:FD": "Nokia",
    "1C:56:FE": "Motorola",
    "5C:51:88": "Motorola",
    "68:CC:A8": "OnePlus",
    "9C:2F:9D": "OnePlus",
    "90:B6:86": "Oppo",
    "B4:CB:57": "Oppo",
    "94:0C:98": "Vivo",
    "70:F8:2B": "Vivo",
    "78:1F:DB": "Realme",
    "C8:14:79": "Realme",
    "E0:67:81": "Honor",
    "AC:37:43": "Honor",
    "D0:C5:D3": "Alcatel",
    "00:23:32": "Alcatel",
    "00:04:ED": "D-Link",
    "1C:BD:B9": "D-Link",
    "C4:A3:66": "D-Link",
    "84:16:F9": "Belkin",
    "08:86:3B": "Belkin",
    "00:05:CA": "Linksys",
    "48:5D:36": "Linksys",
}


def normalize_mac(mac: str) -> str:
    """توحيد MAC إلى صيغة AA:BB:CC:DD:EE:FF."""
    cleaned = "".join(c for c in mac.upper() if c in "0123456789ABCDEF")
    if len(cleaned) != 12:
        return mac.upper().strip()
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def _load_cache(cache_path: str) -> dict:
    try:
        p = Path(cache_path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.debug("تعذّر قراءة cache الـ OUI", exc_info=True)
    return {}


def _save_cache(cache_path: str, cache: dict) -> None:
    try:
        p = Path(cache_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("تعذّر حفظ cache الـ OUI", exc_info=True)


def lookup(mac: str, cache_path: str = "data/oui_cache.json") -> str | None:
    """البحث عن الشركة: cache أولاً، ثم OUI_DB، ثم API اختيارياً.

    يعمل offline تماماً — فشل النت يعيد None دون انهيار.
    """
    oui = normalize_mac(mac)[:8]
    if len(oui) != 8:
        return None

    cache = _load_cache(cache_path)
    if oui in cache:
        return cache[oui]
    if oui in OUI_DB:
        return OUI_DB[oui]

    # محاولة API (اختيارية ومحمية)
    try:
        import requests

        resp = requests.get(f"https://api.macvendors.com/{mac}", timeout=5)
        if resp.status_code == 200:
            vendor = resp.text.strip()
            if vendor:
                cache[oui] = vendor
                _save_cache(cache_path, cache)
                return vendor
    except Exception:  # noqa: BLE001 - لا نت متاح أو خطأ: نتجاهل
        logger.debug("API الـ OUI فشل — وضع offline", exc_info=True)
    return None
