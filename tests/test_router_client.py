"""اختبارات عميل الراوتر (parse_row حقيقي + تدفقات بـ mock driver)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.router_client import RouterClient
from core.types import DeviceRow

CFG = {"router": {"url": "http://192.168.1.1", "username": "admin",
                  "password": "admin", "timeout": 15},
       "scan": {}}


def test_parse_row_normal():
    r = RouterClient.parse_row(["MyPhone", "192.168.1.5", "8c:1f:5a:11:22:33"])
    assert isinstance(r, DeviceRow)
    assert r.hostname == "MyPhone"
    assert r.ip == "192.168.1.5"
    assert r.mac == "8C:1F:5A:11:22:33"


def test_parse_row_skips_header():
    assert RouterClient.parse_row(["Host Name", "IP Address", "MAC Address"]) is None
    assert RouterClient.parse_row(["", "   "]) is None
    assert RouterClient.parse_row([]) is None


def test_parse_row_mac_with_dashes():
    r = RouterClient.parse_row(["PC", "192.168.1.7", "aa-bb-cc-dd-ee-ff"])
    assert r is not None and r.mac == "AA:BB:CC:DD:EE:FF"


def _mock_cell(text):
    c = MagicMock()
    c.text = text
    return c


def _mock_row(cells):
    r = MagicMock()
    r.find_elements.return_value = [_mock_cell(t) for t in cells]
    return r


def test_read_devices_parses_and_dedups():
    driver = MagicMock()
    driver.find_elements.return_value = [
        _mock_row(["Host Name", "IP", "MAC"]),
        _mock_row(["MyPhone", "192.168.1.5", "8C:1F:5A:11:22:33"]),
        _mock_row(["MyPhone", "192.168.1.5", "8C:1F:5A:11:22:33"]),  # مكرر
        _mock_row(["Phone", "192.168.1.9", "3C:06:30:AA:BB:CC"]),
    ]
    client = RouterClient(driver, CFG, debug_folder="/tmp")
    devices = client.read_devices()
    assert len(devices) == 2
    assert devices[0].hostname == "MyPhone"
    assert devices[1].mac == "3C:06:30:AA:BB:CC"


def _mock_driver():
    """driver وهمي تتعامل معه شروط Selenium 4.51 (is_displayed() == True)."""
    driver = MagicMock()
    el = driver.find_element.return_value
    el.is_displayed.return_value = True
    el.is_enabled.return_value = True
    return driver


def test_login_success_flow():
    driver = _mock_driver()
    client = RouterClient(driver, CFG, debug_folder="/tmp")
    assert client.login() is True
    driver.get.assert_called_once_with("http://192.168.1.1")


def test_login_skips_when_already_logged_in():
    """الجلسة مسجلة دخول مسبقاً: لا نموذج دخول → تخطٍّ فوري بلا ضغط أزرار."""
    from selenium.common.exceptions import NoSuchElementException

    driver = MagicMock()

    def find_element(by, value):
        if "Setup" in value or "logout" in value.lower():
            el = MagicMock()
            el.is_displayed.return_value = True
            return el
        raise NoSuchElementException("no login form")

    driver.find_element.side_effect = find_element
    client = RouterClient(driver, CFG, debug_folder="/tmp")
    assert client.login() is True
    driver.get.assert_called_once_with("http://192.168.1.1")


def test_open_dhcp_page_flow():
    driver = _mock_driver()
    client = RouterClient(driver, CFG, debug_folder="/tmp")
    assert client.open_dhcp_page() is True


def test_open_show_client_flow():
    driver = _mock_driver()
    driver.window_handles = ["main"]
    # صفوف جدول موجودة → الانتظارات الذكية تُحسم فوراً
    driver.find_elements.return_value = [MagicMock()]
    client = RouterClient(driver, CFG, debug_folder="/tmp")
    assert client.open_show_client() is True
