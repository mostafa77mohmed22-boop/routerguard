"""أدوات Selenium مشتركة (منقولة ومحسّنة من السكربت الأصلي)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("routerguard.utils")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def click_element(driver, element) -> None:
    """نقرة عادية، وعند فشلها نقرة JavaScript (منطق السكربت الأصلي)."""
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)


def find_clickable(driver, xpath_list: Iterable[str], timeout: int = 5):
    """يجرب قائمة XPaths ويعيد أول عنصر قابل للنقر، أو None."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    for xpath in xpath_list:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
        except Exception:
            continue
    return None


def save_debug_files(driver, label: str, folder: str | Path = "logs") -> Optional[Path]:
    """يحفظ لقطة شاشة + HTML عند الخطأ (تشخيص)."""
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot = folder / f"debug_{label}_{timestamp}.png"
        html_path = folder / f"debug_{label}_{timestamp}.html"
        driver.save_screenshot(str(screenshot))
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log.warning("حُفظت ملفات التشخيص: %s , %s", screenshot, html_path)
        return screenshot
    except Exception as exc:  # لا نريد أن يسقط التشخيص نفسه الفحص
        log.error("تعذر حفظ ملفات التشخيص: %s", exc)
        return None
