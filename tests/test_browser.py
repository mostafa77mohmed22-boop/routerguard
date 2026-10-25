"""اختبار منطق اختيار الدرايفر في core/browser.py (بـ mocks كاملة)."""
import os
import sys
import types
from unittest.mock import MagicMock, patch


def _install_fake_selenium(monkeypatch):
    """يثبت وحدات selenium وهمية في sys.modules قبل استيراد core.browser."""
    selenium = types.ModuleType("selenium")
    webdriver_mod = types.ModuleType("selenium.webdriver")
    chrome_mod = types.ModuleType("selenium.webdriver.chrome")
    options_mod = types.ModuleType("selenium.webdriver.chrome.options")
    service_mod = types.ModuleType("selenium.webdriver.chrome.service")

    fake_webdriver = MagicMock()
    fake_options_cls = MagicMock()
    fake_service_cls = MagicMock()

    webdriver_mod.Chrome = fake_webdriver
    options_mod.Options = fake_options_cls
    service_mod.Service = fake_service_cls

    wdm_mod = types.ModuleType("webdriver_manager.chrome")
    fake_manager_cls = MagicMock()
    wdm_mod.ChromeDriverManager = fake_manager_cls

    monkeypatch.setitem(sys.modules, "selenium", selenium)
    monkeypatch.setitem(sys.modules, "selenium.webdriver", webdriver_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome", chrome_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome.options", options_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome.service", service_mod)
    monkeypatch.setitem(sys.modules, "webdriver_manager", types.ModuleType("webdriver_manager"))
    monkeypatch.setitem(sys.modules, "webdriver_manager.chrome", wdm_mod)

    for mod in ("core", "core.browser"):
        sys.modules.pop(mod, None)

    return fake_webdriver, fake_options_cls, fake_service_cls, fake_manager_cls


def test_manual_driver_path_used_when_file_exists(monkeypatch, tmp_path):
    fake_webdriver, _, fake_service_cls, fake_manager_cls = _install_fake_selenium(monkeypatch)
    from core.browser import create_driver

    driver_file = tmp_path / "chromedriver.exe"
    driver_file.write_bytes(b"fake")

    create_driver(headless=True, driver_path=str(driver_file))

    # يجب استخدام المسار اليدوي مباشرة وعدم استدعاء webdriver-manager
    fake_service_cls.assert_called_once_with(str(driver_file))
    fake_manager_cls.assert_not_called()
    assert fake_webdriver.called


def test_webdriver_manager_used_when_no_driver_path(monkeypatch):
    fake_webdriver, _, fake_service_cls, fake_manager_cls = _install_fake_selenium(monkeypatch)
    from core.browser import create_driver

    fake_manager_cls.return_value.install.return_value = "/tmp/cached/chromedriver"

    create_driver(headless=True, driver_path=None)

    fake_manager_cls.assert_called_once_with()
    fake_service_cls.assert_called_once_with("/tmp/cached/chromedriver")
    assert fake_webdriver.called


def test_missing_manual_path_falls_back_to_manager(monkeypatch):
    _, _, _, fake_manager_cls = _install_fake_selenium(monkeypatch)
    from core.browser import create_driver

    fake_manager_cls.return_value.install.return_value = "/tmp/cached/chromedriver"

    create_driver(headless=True, driver_path="/nonexistent/chromedriver.exe")

    # المسار غير موجود → fallback للتنزيل التلقائي
    fake_manager_cls.assert_called_once_with()


# ---------- اختبارات BrowserSession ----------

def _make_session(monkeypatch, **kwargs):
    """جلسة بـ create_driver وهمي يعدّ مرات الإنشاء."""
    from core import browser as browser_mod
    calls = {"n": 0, "quits": 0}

    class FakeDriver:
        def quit(self):
            calls["quits"] += 1

    def fake_create_driver(**kw):
        calls["n"] += 1
        return FakeDriver()

    monkeypatch.setattr(browser_mod, "create_driver", fake_create_driver)
    from core.browser import BrowserSession
    return BrowserSession(**kwargs), calls


def test_session_reuses_driver(monkeypatch):
    session, calls = _make_session(monkeypatch)
    d1 = session.get_driver()
    d2 = session.get_driver()
    d3 = session.get_driver()
    assert d1 is d2 is d3
    assert calls["n"] == 1  # أُنشئ مرة واحدة فقط
    assert calls["quits"] == 0
    session.close()


def test_session_recreates_after_failure(monkeypatch):
    session, calls = _make_session(monkeypatch)
    d1 = session.get_driver()
    session.mark_failed()
    assert calls["quits"] == 1
    d2 = session.get_driver()
    assert d2 is not d1
    assert calls["n"] == 2
    session.close()


def test_session_preventive_recycle(monkeypatch):
    session, calls = _make_session(monkeypatch, recycle_every=3)
    d1 = session.get_driver()
    session.release()  # 1
    session.release()  # 2
    assert session.get_driver() is d1
    session.release()  # 3 → إعادة تشغيل وقائية
    assert calls["quits"] == 1
    d2 = session.get_driver()
    assert d2 is not d1
    assert calls["n"] == 2
    session.close()


def test_session_close_is_idempotent(monkeypatch):
    session, calls = _make_session(monkeypatch)
    session.get_driver()
    session.close()
    session.close()
    assert calls["quits"] == 1


def test_session_reduces_driver_creation():
    """قياس الفرق: 60 فحصاً — إنشاء جديد لكل فحص مقابل جلسة مشتركة.

    قبل: 60 إنشاء. بعد (recycle_every=20): 3 إنشاءات فقط.
    """
    from core.browser import BrowserSession
    created = {"n": 0}

    class FakeDriver:
        def quit(self):
            pass

    import core.browser as browser_mod
    real = browser_mod.create_driver
    browser_mod.create_driver = lambda **kw: (created.__setitem__("n", created["n"] + 1),
                                              FakeDriver())[1]
    try:
        # المحاكاة القديمة: driver جديد لكل فحص
        old_way = 0
        for _ in range(60):
            browser_mod.create_driver()
            old_way += 1
        assert old_way == 60

        # الطريقة الجديدة: جلسة مشتركة مع تدوير كل 20
        created["n"] = 0
        session = BrowserSession(recycle_every=20)
        for _ in range(60):
            session.get_driver()
            session.release()
        session.close()
        assert created["n"] == 3
        print(f"\nإنشاء الـ driver: قبل={old_way} بعد={created['n']} "
              f"(توفير {(1 - created['n']/old_way)*100:.0f}%)")
    finally:
        browser_mod.create_driver = real
