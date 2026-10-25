"""مصنع متصفح Selenium — يعمل headless افتراضياً للتشغيل الخلفي."""
from __future__ import annotations

import logging
import os
import shutil

log = logging.getLogger("routerguard.browser")


def create_driver(headless: bool = True, timeout: int = 10,
                  driver_path: str | None = None):
    """ينشئ WebDriver لكروم.

    driver_path: مسار chromedriver.exe يدوي (مثل السكربت الأصلي) —
    يُستخدم مباشرة بدون تنزيل. إذا لم يُعطَ أو الملف غير موجود،
    يستخدم webdriver-manager للتنزيل التلقائي.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as exc:
        raise RuntimeError(
            "مكتبتا selenium و webdriver-manager غير مثبتتين. "
            "ثبّتهما بـ: pip install selenium webdriver-manager"
        ) from exc

    if not (shutil.which("google-chrome") or shutil.which("chrome")
            or shutil.which("chromium") or shutil.which("chromium-browser")):
        log.warning("لم يتم العثور على متصفح Chrome/Chromium في PATH — قد يفشل التشغيل")

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    else:
        options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    if driver_path and os.path.exists(driver_path):
        log.info("استخدام chromedriver يدوي: %s", driver_path)
        service = Service(driver_path)
    else:
        if driver_path:
            log.warning("مسار الدرايفر غير موجود (%s) — سيُستخدم webdriver-manager",
                        driver_path)
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(
        service=service,
        options=options,
    )
    driver.implicitly_wait(3)
    driver.set_page_load_timeout(timeout * 3)
    log.info("تم إنشاء متصفح Chrome (headless=%s)", headless)
    return driver


class BrowserSession:
    """جلسة متصفح تُعاد استخدامها عبر فحوصات متعددة.

    فتح Chrome جديد لكل فحص بطيء وثقيل على الرام؛ هذه الفئة تنشئ
    الـ driver مرة واحدة وتعيد استخدامه، مع:
    - إعادة إنشاء تلقائية عند فشل فحص (mark_failed)
    - إعادة تشغيل وقائية كل recycle_every فحصاً لتجنب تسرب الذاكرة

    تُستخدم في وضع run المستمر فقط؛ وضع scan (مرة واحدة) يبقى
    ينشئ driver ثم يغلقه كما كان.
    """

    def __init__(self, headless: bool = True, driver_path: str | None = None,
                 recycle_every: int = 20, timeout: int = 10):
        self._headless = headless
        self._driver_path = driver_path
        self._recycle_every = max(1, int(recycle_every))
        self._timeout = timeout
        self._driver = None
        self._uses = 0
        self.created_count = 0  # مفيد للتشخيص والاختبارات

    def get_driver(self):
        """يعيد الـ driver الحالي، وينشئه عند أول استخدام أو بعد فشل."""
        if self._driver is None:
            self._driver = create_driver(headless=self._headless,
                                         timeout=self._timeout,
                                         driver_path=self._driver_path)
            self._uses = 0
            self.created_count += 1
        return self._driver

    def release(self) -> None:
        """يُستدعى بعد فحص ناجح؛ يعيد التدوير الوقائي كل N فحصاً."""
        self._uses += 1
        if self._uses >= self._recycle_every:
            log.info("إعادة تشغيل وقائية للمتصفح بعد %d فحصاً", self._uses)
            self.close()

    def mark_failed(self) -> None:
        """يُستدعى بعد فحص فاشل؛ يغلق الجلسة لتُعاد إنشاؤها نظيفة."""
        log.warning("فشل فحص — سيُعاد إنشاء جلسة المتصفح")
        self.close()

    def close(self) -> None:
        """يغلق المتصفح نهائياً."""
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
            self._uses = 0

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
