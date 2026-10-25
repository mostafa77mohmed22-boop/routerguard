"""عميل الراوتر: تسجيل الدخول والتنقل وقراءة جدول أجهزة DHCP.

المنطق منقول من السكربت الأصلي (python_router_monitor.py) مع تنظيمه
في كلاس قابل للاختبار، وإرجاع صفوف منظمة بدل نصوص خام.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from core.types import DeviceRow
from core.utils import click_element, find_clickable, save_debug_files

log = logging.getLogger("routerguard.router")

MAC_RE = re.compile(r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

HEADER_WORDS = {
    "hostname", "host name", "ip address", "mac address",
    "client name", "lease time", "status", "device name",
}

# ثوابت XPath تُستخدم في الانتظارات الذكية
USERNAME_XPATH = (
    "//input[not(@type='password') and not(@type='hidden') and "
    "not(@type='submit') and not(@type='button') and not(@type='reset')]"
)
PASSWORD_XPATH = "//input[@type='password']"
# علامات تُظهر أن الجلسة مسجّلة دخول مسبقاً (صفحة ما بعد الدخول)
LOGGED_IN_MARKERS = [
    "//*[normalize-space()='Setup']",
    "//*[contains(translate(normalize-space(), 'LOGOUT', 'logout'), 'logout')]",
]
CONTENT_IFRAME_ID = "contentIframe"
TABLE_ROWS_XPATH = "//table//tr"


class RouterClient:
    """يتعامل مع واجهة الراوتر عبر Selenium."""

    def __init__(self, driver, cfg: dict, debug_folder: str = "logs"):
        self.driver = driver
        self.cfg = cfg["router"]
        self.scan_cfg = cfg.get("scan", {})
        self.debug_folder = debug_folder

    # ---------- الخطوات ----------

    def _is_logged_in(self, timeout: int = 3) -> bool:
        """يتحقق سريعاً من علامات صفحة ما بعد تسجيل الدخول."""
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        for xpath in LOGGED_IN_MARKERS:
            try:
                WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((By.XPATH, xpath)))
                return True
            except TimeoutException:
                continue
        return False

    def login(self) -> bool:
        """تسجيل الدخول إلى صفحة الراوتر.

        ذكي: إذا كانت الجلسة مسجّلة دخول مسبقاً (وضع run مع إعادة
        استخدام المتصفح) يتخطى النموذج فوراً بدل انتظار 15 ثانية وفشل.
        """
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            url = self.cfg["url"]
            timeout = int(self.cfg.get("timeout", 15))
            log.info("فتح صفحة الراوتر %s", url)
            self.driver.get(url)

            # فحص سريع (4 ثوانٍ) لنموذج الدخول
            try:
                username_field = WebDriverWait(self.driver, 4).until(
                    EC.presence_of_element_located((By.XPATH, USERNAME_XPATH)))
            except TimeoutException:
                username_field = None

            if username_field is None:
                # ربما الجلسة مسجّلة دخول مسبقاً — تحقق قبل إضاعة الوقت
                if self._is_logged_in(timeout=3):
                    log.info("الجلسة مسجّلة دخول مسبقاً — تم تخطّي تسجيل الدخول")
                    return True
                # الصفحة بطيئة على الأرجح — انتظر النموذج بالمهلة الكاملة
                log.info("نموذج الدخول لم يظهر سريعاً — انتظار بالمهلة الكاملة")
                username_field = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((By.XPATH, USERNAME_XPATH)))

            password_field = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, PASSWORD_XPATH)))

            username_field.clear()
            username_field.send_keys(self.cfg["username"])
            password_field.clear()
            # كلمة المرور لا تُطبع أبداً في الـ logs
            password_field.send_keys(self.cfg["password"])

            login_button = find_clickable(self.driver, [
                "//input[@type='submit']",
                "//input[contains(translate(@value, 'LOGIN', 'login'), 'login')]",
                "//button[contains(translate(normalize-space(), 'LOGIN', 'login'), 'login')]",
            ], timeout=5)
            if login_button is None:
                raise RuntimeError("لم يتم العثور على زر Login")

            click_element(self.driver, login_button)
            # انتظار ذكي لعلامة ما بعد الدخول بدل sleep(4) الثابت
            if self._is_logged_in(timeout=6):
                log.info("تم تسجيل الدخول بنجاح")
            else:
                log.warning("لم تظهر علامة ما بعد الدخول — المتابعة على أي حال")
            return True
        except Exception as exc:
            log.error("خطأ في تسجيل الدخول: %s", exc)
            save_debug_files(self.driver, "login_error", self.debug_folder)
            return False

    def open_dhcp_page(self) -> bool:
        """التنقل: Setup > LAN > DHCP.

        بلا انتظارات ثابتة: find_clickable ينتظر ظهور كل عنصر بنفسه،
        وبعد DHCP ننتظر الـ iframe مباشرة بدل sleep(3).
        """
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            setup = find_clickable(self.driver, [
                "//a[normalize-space()='Setup']",
                "//*[normalize-space()='Setup']",
            ], timeout=8)
            if setup is None:
                raise RuntimeError("لم أجد زر Setup")
            click_element(self.driver, setup)

            lan = find_clickable(self.driver, [
                "//h3//a[normalize-space()='LAN']",
                "//*[normalize-space()='LAN']",
            ], timeout=8)
            if lan is None:
                raise RuntimeError("لم أجد قائمة LAN")
            click_element(self.driver, lan)

            dhcp = find_clickable(self.driver, [
                "//a[@target='contentIframe' and normalize-space()='DHCP']",
                "//a[contains(@href, 'dhcpd.htm')]",
                "//a[normalize-space()='DHCP']",
            ], timeout=8)
            if dhcp is None:
                raise RuntimeError("لم أجد صفحة DHCP")
            click_element(self.driver, dhcp)
            # انتظار ظهور الـ iframe بدل sleep(3) — غير قاتل إن لم يظهر
            try:
                WebDriverWait(self.driver, 6).until(
                    EC.presence_of_element_located((By.ID, CONTENT_IFRAME_ID)))
            except TimeoutException:
                pass
            log.info("تم الوصول إلى صفحة DHCP")
            return True
        except Exception as exc:
            log.error("خطأ أثناء فتح DHCP: %s", exc)
            save_debug_files(self.driver, "dhcp_error", self.debug_folder)
            return False

    def open_show_client(self) -> bool:
        """فتح زر Show Client داخل iframe ثم التعامل مع النافذة الجديدة.

        بلا انتظارات ثابتة: ننتظر (نافذة جديدة أو صفوف جدول) أيهما ظهر أولاً.
        """
        from selenium.common.exceptions import TimeoutException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            self.driver.switch_to.default_content()
            wait = WebDriverWait(self.driver, 15)
            iframe = wait.until(EC.presence_of_element_located((By.ID, CONTENT_IFRAME_ID)))
            self.driver.switch_to.frame(iframe)

            show_client = find_clickable(self.driver, [
                "//input[contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show client')]",
                "//input[contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show')]",
                "//button[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show client')]",
                "//a[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show client')]",
                "//*[contains(translate(normalize-space(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'show client')]",
            ], timeout=8)
            if show_client is None:
                raise RuntimeError("لم أجد زر Show Client داخل صفحة DHCP")

            windows_before = self.driver.window_handles[:]
            click_element(self.driver, show_client)

            # نافذة جديدة أو صفوف جدول داخل نفس الصفحة — أيهما أولاً (بدل sleep(3))
            def _client_list_ready(d):
                if len(d.window_handles) > len(windows_before):
                    return True
                try:
                    return len(d.find_elements(By.XPATH, "//table//tr[td]")) > 0
                except Exception:
                    return False

            try:
                WebDriverWait(self.driver, 8).until(_client_list_ready)
            except TimeoutException:
                pass
            self.driver.switch_to.default_content()

            if len(self.driver.window_handles) > len(windows_before):
                self.driver.switch_to.window(self.driver.window_handles[-1])
                log.info("قائمة الأجهزة فُتحت في نافذة جديدة")
            else:
                iframe = wait.until(EC.presence_of_element_located((By.ID, CONTENT_IFRAME_ID)))
                self.driver.switch_to.frame(iframe)
                log.info("قائمة الأجهزة ظهرت داخل صفحة DHCP")
            # انتظار صفوف الجدول بدل sleep(2) — غير قاتل
            try:
                WebDriverWait(self.driver, 5).until(
                    lambda d: len(d.find_elements(By.XPATH, TABLE_ROWS_XPATH)) > 0)
            except TimeoutException:
                pass
            return True
        except Exception as exc:
            log.error("خطأ عند فتح Show Client: %s", exc)
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            save_debug_files(self.driver, "show_client_error", self.debug_folder)
            return False

    # ---------- قراءة الجدول ----------

    @staticmethod
    def parse_row(cells: list[str]) -> Optional[DeviceRow]:
        """يحول خلايا صف جدول إلى DeviceRow منظمة."""
        texts = [c.strip() for c in cells if c.strip()]
        if not texts:
            return None
        joined = " | ".join(texts)
        lowered = joined.lower()
        if any(w in lowered for w in HEADER_WORDS):
            return None  # صف عنوان الجدول

        mac_m = MAC_RE.search(joined)
        ip_m = IP_RE.search(joined)
        mac = mac_m.group(0).upper().replace("-", ":") if mac_m else ""
        ip = ip_m.group(0) if ip_m else ""
        # الاسم = أول خلية ليست MAC ولا IP
        hostname = ""
        for t in texts:
            if t == mac_m.group(0) if mac_m else False:
                continue
            if ip_m and t == ip_m.group(0):
                continue
            if MAC_RE.fullmatch(t) or IP_RE.fullmatch(t):
                continue
            hostname = t
            break

        return DeviceRow(hostname=hostname, ip=ip, mac=mac, raw=joined)

    def read_devices(self) -> list[DeviceRow]:
        """يقرأ كل صفوف جدول الأجهزة من الصفحة الحالية."""
        from selenium.webdriver.common.by import By

        devices: list[DeviceRow] = []
        try:
            rows = self.driver.find_elements(By.XPATH, "//table//tr")
            for row in rows:
                cells = [c.text for c in row.find_elements(By.XPATH, ".//td")]
                parsed = self.parse_row(cells)
                if parsed and all(d.raw != parsed.raw for d in devices):
                    devices.append(parsed)
        except Exception as exc:
            log.error("خطأ أثناء قراءة جدول الأجهزة: %s", exc)
        log.info("قُرئ %d جهازاً من جدول DHCP", len(devices))
        return devices

    # ---------- فحص كامل ----------

    def full_scan(self) -> tuple[list[DeviceRow], str]:
        """ينفذ الدورة الكاملة. يعيد (الأجهزة, رسالة خطأ أو '')."""
        if not self.login():
            return [], "فشل تسجيل الدخول"
        if not self.open_dhcp_page():
            return [], "فشل فتح صفحة DHCP"
        if not self.open_show_client():
            return [], "فشل فتح Show Client"
        devices = self.read_devices()
        if not devices:
            save_debug_files(self.driver, "no_devices", self.debug_folder)
            return [], "لم يُعثر على جدول الأجهزة"
        return devices, ""
