"""مراقب الإنترنت: ping للبوابة وDNS عام، قياس سرعة، وسجل الانقطاعات."""
from __future__ import annotations

import logging
import platform
import subprocess
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("routerguard.internet")


def ping(host: str, timeout: int = 2) -> Optional[float]:
    """يرسل ping واحداً. يعيد زمن الاستجابة بالمللي ثانية أو None عند الفشل."""
    is_windows = platform.system().lower() == "windows"
    count_flag = "-n" if is_windows else "-c"
    timeout_flag = "-w" if is_windows else "-W"
    # ملاحظة: -w في ويندوز بالمللي ثانية، بينما -W في لينكس بالثواني
    timeout_value = str(timeout * 1000) if is_windows else str(timeout)
    try:
        result = subprocess.run(
            ["ping", count_flag, "1", timeout_flag, timeout_value, host],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if result.returncode == 0:
            import re
            # يدعم الإنجليزية (time=5ms) والعربية (الوقت=5 م.ث)
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ms|م\.ث)", result.stdout)
            if m:
                return float(m.group(1))
            return 0.0  # نجح لكن لم نلتقط الزمن
        return None
    except Exception as exc:
        log.debug("فشل ping إلى %s: %s", host, exc)
        return None


class InternetMonitor:
    """يفحص الاتصال ويتتبع الانقطاعات في قاعدة البيانات."""

    def __init__(self, db, cfg: dict):
        self.db = db
        net = cfg.get("internet", {})
        self.enabled = bool(net.get("enabled", True))
        self.gateway = net.get("gateway", "192.168.1.1")
        self.dns_targets = net.get("dns_targets", ["8.8.8.8"])
        self.speedtest_enabled = bool(net.get("speedtest_enabled", False))
        self.speedtest_interval = timedelta(
            minutes=int(net.get("speedtest_interval_minutes", 60))
        )
        self._outage_start: Optional[datetime] = None
        self._last_speedtest: Optional[datetime] = None

    def check(self, at: Optional[datetime] = None) -> dict:
        """فحص واحد. يعيد dict بالحالة ويسجل بداية/نهاية الانقطاعات."""
        at = at or datetime.now()
        gw_ms = ping(self.gateway)
        dns_ok = any(ping(t) is not None for t in self.dns_targets)
        online = gw_ms is not None and dns_ok

        if not online and self._outage_start is None:
            self._outage_start = at
            self.db.record_event("outage_start", "critical",
                                 "انقطع الاتصال بالإنترنت", extra="")
            log.warning("انقطاع الإنترنت بدأ عند %s", at)
        elif online and self._outage_start is not None:
            self.db.record_outage(self._outage_start, at)
            mins = (at - self._outage_start).total_seconds() / 60
            self.db.record_event("outage_end", "info",
                                 f"عاد الاتصال بعد انقطاع {mins:.1f} دقيقة")
            log.info("انتهى الانقطاع (مدته %.1f دقيقة)", mins)
            self._outage_start = None

        result = {
            "online": online,
            "gateway_ms": gw_ms,
            "dns_ok": dns_ok,
            "in_outage": self._outage_start is not None,
            "at": at,
        }

        if online and self.speedtest_enabled and self._due_for_speedtest(at):
            speed = self.measure_speed()
            if speed:
                result.update(speed)
                self.db.record_speed(at, speed["down_mbps"],
                                     speed["up_mbps"], speed["ping_ms"])
                self._last_speedtest = at

        return result

    def _due_for_speedtest(self, at: datetime) -> bool:
        return (self._last_speedtest is None
                or at - self._last_speedtest >= self.speedtest_interval)

    @staticmethod
    def measure_speed() -> Optional[dict]:
        """قياس السرعة عبر speedtest-cli (إن كان مثبتاً)."""
        try:
            import speedtest
        except ImportError:
            log.warning("speedtest-cli غير مثبت — تم تخطي قياس السرعة")
            return None
        try:
            st = speedtest.Speedtest()
            st.get_best_server()
            down = st.download() / 1_000_000
            up = st.upload() / 1_000_000
            ping_ms = st.results.ping
            log.info("السرعة: %.1f down / %.1f up Mbps (ping %.0f ms)",
                     down, up, ping_ms)
            return {"down_mbps": round(down, 1),
                    "up_mbps": round(up, 1), "ping_ms": round(ping_ms, 1)}
        except Exception as exc:
            log.error("فشل قياس السرعة: %s", exc)
            return None

    def uptime_percent(self, hours: int = 24) -> Optional[float]:
        """نسبة الـ uptime خلال آخر N ساعة من سجل الانقطاعات."""
        since = datetime.now() - timedelta(hours=hours)
        outages = self.db.list_outages(since)
        down_sec = sum(o["duration_sec"] for o in outages)
        if self._outage_start is not None:
            down_sec += (datetime.now() - self._outage_start).total_seconds()
        total = hours * 3600
        return round(100.0 * (total - down_sec) / total, 2)
