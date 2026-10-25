"""اختبارات أداة OUI (لا شبكة حقيقية)."""
from __future__ import annotations

from tools.oui import OUI_DB, lookup, normalize_mac


def test_normalize_mac():
    assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("aabb.ccdd.eeff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"


def test_oui_db_has_expected_vendors():
    for vendor in [
        "Apple", "Samsung", "Xiaomi", "Huawei", "TP-Link", "Intel",
        "Qualcomm", "Realtek", "MediaTek", "Espressif", "Raspberry Pi",
        "Google", "Amazon", "Microsoft", "Sony", "LG", "Dell", "HP",
        "Lenovo", "Asus", "Cisco", "Netgear", "Tenda", "ZTE", "Nokia",
        "Motorola", "OnePlus", "Oppo", "Vivo", "Realme",
    ]:
        assert vendor in OUI_DB.values(), f"مفقود: {vendor}"
    assert len(OUI_DB) >= 50


def test_lookup_from_dict(tmp_path):
    cache = str(tmp_path / "oui.json")
    assert lookup("B8:27:EB:12:34:56", cache_path=cache) == "Raspberry Pi"


def test_lookup_api_failure_returns_none(tmp_path, monkeypatch):
    """requests.get مُموّهة للفشل: يجب أن يعيد None دون انهيار."""

    def fake_get(*a, **k):
        raise ConnectionError("no network")

    monkeypatch.setattr("requests.get", fake_get)
    # OUI غير موجود في القاموس لضمان الوصول لمسار الـ API
    assert lookup("FF:EE:DD:CC:BB:AA", cache_path=str(tmp_path / "oui.json")) is None


def test_lookup_api_success_caches(tmp_path, monkeypatch):
    class Resp:
        status_code = 200
        text = "TestVendor Inc"

    monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
    cache = str(tmp_path / "oui.json")
    assert lookup("FF:EE:DD:CC:BB:AA", cache_path=cache) == "TestVendor Inc"
    # المرة الثانية من الـ cache حتى لو فشل الـ API
    def boom(*a, **k):
        raise AssertionError("يجب ألا يُستدعى الـ API")

    monkeypatch.setattr("requests.get", boom)
    assert lookup("FF:EE:DD:CC:BB:AA", cache_path=cache) == "TestVendor Inc"
