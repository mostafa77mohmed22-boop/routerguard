#!/usr/bin/env python3
"""RouterGuard — حارس الراوتر الاحترافي.

الأوامر:
    python main.py init        إنشاء config.yaml والمجلدات
    python main.py run         التشغيل المستمر (خلفي)
    python main.py scan        فحص واحد ثم خروج
    python main.py status      ملخص الحالة
    python main.py devices     قائمة الأجهزة المسجلة
    python main.py block <mac> حظر جهاز
    python main.py unblock <mac>
    python main.py report      التقرير اليومي + تصدير CSV
    python main.py dashboard   تشغيل لوحة التحكم
    python main.py demo        عرض تجريبي ببيانات وهمية
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import load_config, project_root  # noqa: E402
from core.types import DeviceRow, ScanOutcome  # noqa: E402

log = logging.getLogger("routerguard")


def setup_logging(cfg: dict) -> None:
    level = getattr(logging, str(cfg.get("logging", {}).get("level", "INFO")).upper(),
                    logging.INFO)
    logfile = project_root() / cfg.get("logging", {}).get("file", "logs/routerguard.log")
    logfile.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(level=level, handlers=handlers, format=fmt._fmt,
                        datefmt="%Y-%m-%d %H:%M:%S")
    for h in logging.getLogger().handlers:
        h.setFormatter(fmt)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


class RouterGuardApp:
    """يربط كل المكونات: الإعدادات، التخزين، التنبيهات، المراقبة."""

    def __init__(self, config_path: str | None = None):
        self.root = project_root()
        self.cfg = load_config(config_path)
        setup_logging(self.cfg)

        (self.root / "data").mkdir(exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)

        from storage.database import Database
        db_path = self.root / self.cfg.get("storage", {}).get("path", "data/routerguard.db")
        self.db = Database(str(db_path))

        from alerts import build_alert_manager
        self.alerts, self.escalation = build_alert_manager(self.cfg, log)

        from tools.oui import lookup as oui_lookup
        self.oui_lookup = oui_lookup

        from monitors.device_monitor import DeviceMonitor
        from monitors.internet_monitor import InternetMonitor
        from monitors.new_join_watcher import NewJoinWatcher
        self.devices = DeviceMonitor(self.db, self.cfg,
                                     oui_lookup=oui_lookup,
                                     data_dir=self.root / "data")
        self.internet = InternetMonitor(self.db, self.cfg)
        self.new_join = NewJoinWatcher(self.alerts.notify, oui_lookup=oui_lookup)

        self._telegram_bot = None
        self._start_telegram_bot()

        retention = int(self.cfg.get("storage", {}).get("retention_days", 90))
        try:
            pruned = self.db.prune(retention)
            if any(pruned.values()):
                log.info("تنظيف البيانات القديمة: %s", pruned)
        except Exception as exc:
            log.error("فشل تنظيف البيانات: %s", exc)

    # ---------- تيليجرام ----------

    def _start_telegram_bot(self) -> None:
        tg = self.cfg.get("alerts", {}).get("telegram", {})
        if not tg.get("enabled"):
            return
        token = tg.get("bot_token") or ""
        chat_id = tg.get("chat_id") or ""
        if not token or not chat_id:
            log.warning("تيليجرام مفعّل لكن bot_token/chat_id ناقصان")
            return
        try:
            from alerts.telegram import TelegramCommandBot
            callbacks = {
                "status": lambda args: self._tg_status(),
                "scan": lambda args: self._tg_scan(),
                "devices": lambda args: self._tg_devices(),
                "block": lambda args: self._tg_block(args),
                "events": lambda args: self._tg_events(),
            }
            self._telegram_bot = TelegramCommandBot(token, chat_id, callbacks)
            self._telegram_bot.start()
            log.info("بوت تيليجرام يعمل ويستقبل الأوامر")
        except Exception as exc:
            log.error("فشل تشغيل بوت تيليجرام: %s", exc)

    def _tg_status(self) -> str:
        st = self.get_status()
        c = st["counts"]
        return (
            f"حالة RouterGuard\n"
            f"الراوتر: {'متصل' if st['router_ok'] else 'غير متصل'}\n"
            f"الإنترنت: {'متصل' if st['internet_ok'] else 'منقطع'}\n"
            f"الأجهزة: {c['total']} (مسموح {c['allowed']}، غريب {c['unknown']}، محظور {c['blocked']})\n"
            f"آخر فحص: {st['last_scan'] or 'لم يتم بعد'}\n"
            f"تنبيهات معلقة: {st['pending_escalations']}"
        )

    def _tg_scan(self) -> str:
        res = self.run_scan()
        return "اكتمل الفحص: " + res.get("message", "")

    def _tg_devices(self) -> str:
        devs = self.db.list_devices()
        if not devs:
            return "لا أجهزة مسجلة بعد."
        lines = []
        for d in devs[:20]:
            lines.append(f"- {d['hostname'] or '?'} ({d['mac']}) [{d['status']}]")
        return "الأجهزة:\n" + "\n".join(lines)

    def _tg_block(self, args: list[str]) -> str:
        if not args:
            return "الاستخدام: /block <MAC>"
        ok = self.devices.block_mac(args[0])
        return f"تم حظر {args[0]}" if ok else f"تعذر حظر {args[0]} (تحقق من الصيغة)"

    def _tg_events(self) -> str:
        evs = self.db.list_events(limit=10)
        if not evs:
            return "لا أحداث بعد."
        return "آخر الأحداث:\n" + "\n".join(
            f"- [{e['severity']}] {e['message'][:80]}" for e in evs)

    # ---------- الفحص ----------

    def _default_driver_factory(self):
        from core.browser import create_driver
        scan_cfg = self.cfg.get("scan", {})
        headless = bool(scan_cfg.get("headless", True))
        driver_path = scan_cfg.get("driver_path") or None
        return lambda: create_driver(headless=headless, driver_path=driver_path)

    def run_scan(self, driver_factory=None, driver_session=None) -> dict:
        """ينفذ فحصاً كاملاً واحداً. يعيد dict بالنتيجة.

        driver_session: جلسة متصفح مشتركة (وضع run) — يُعاد استخدام
        نفس الـ driver ولا يُغلق. بدونه يُنشأ driver جديد ويُغلق
        (وضع scan لمرة واحدة).
        """
        from alerts.base import Alert
        from core.router_client import RouterClient

        outcome = ScanOutcome()
        driver = None
        owned = driver_session is None  # هل نملك الـ driver ونغلقه؟
        t0 = time.monotonic()
        try:
            if driver_session is not None:
                driver = driver_session.get_driver()
            else:
                factory = driver_factory or self._default_driver_factory()
                driver = factory()
            client = RouterClient(driver, self.cfg,
                                  debug_folder=str(self.root / "logs"))
            rows, error = client.full_scan()
            duration_ms = int((time.monotonic() - t0) * 1000)
            if error:
                outcome.ok = False
                outcome.error = error
                self.db.record_scan(outcome.at, [], 0, error=error,
                                    duration_ms=duration_ms)
                self.db.record_event("scan_error", "warning",
                                     f"فشل الفحص: {error}")
                self.alerts.notify(Alert("فشل فحص الراوتر", error, "warning"))
                if driver_session is not None:
                    driver_session.mark_failed()
                return {"ok": False, "message": error}

            outcome.devices = rows
            intruders, new_devices, spoofs = self.devices.evaluate(rows, outcome.at)
            outcome.intruders = intruders
            outcome.new_devices = new_devices

            statuses = {r.normalized_mac(): self.devices.classify(r) for r in rows}
            if new_devices:
                self.new_join.watch(new_devices, statuses)

            for intr in intruders:
                mac = intr.normalized_mac()
                vendor = self.oui_lookup(mac)
                sev = "critical" if statuses.get(mac) == "blocked" else "warning"
                msg = (f"جهاز {'محظور' if sev == 'critical' else 'غريب'} متصل الآن:\n"
                       f"الاسم: {intr.hostname or 'بدون اسم'}\n"
                       f"MAC: {mac}\nIP: {intr.ip or '؟'}")
                if vendor:
                    msg += f"\nالشركة: {vendor}"
                alert = Alert("تنبيه أمني — RouterGuard", msg, sev, mac=mac)
                self.alerts.notify(alert)
                if sev == "critical" and self.escalation:
                    self.escalation.raise_critical(alert)

            for spoof in spoofs:
                self.alerts.notify(Alert("اشتباه انتحال MAC", spoof, "critical"))

            # الحارس الليلي
            self._night_guard_check(intruders)

            # فحص الإنترنت
            net = self.internet.check(outcome.at) if self.internet.enabled else {}
            if net and not net["online"]:
                self.alerts.notify(Alert("انقطاع الإنترنت",
                                         "تعذر الوصول للبوابة أو DNS", "critical"))

            self.db.record_scan(outcome.at, rows, len(intruders),
                                duration_ms=duration_ms)
            self._maybe_daily_report()

            msg = (f"{len(rows)} جهازاً، {len(intruders)} غريب/محظور، "
                   f"{len(new_devices)} جديد")
            log.info("اكتمل الفحص: %s (المدة %dms)", msg, duration_ms)
            if driver_session is not None:
                driver_session.release()
            return {"ok": True, "message": msg,
                    "devices": len(rows), "intruders": len(intruders)}
        except Exception as exc:
            log.exception("خطأ غير متوقع في الفحص")
            if driver_session is not None:
                driver_session.mark_failed()
            return {"ok": False, "message": str(exc)}
        finally:
            if owned and driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _night_guard_check(self, intruders: list[DeviceRow]) -> None:
        from alerts.base import Alert
        ng = self.cfg.get("night_guard", {})
        if not ng.get("enabled") or not intruders:
            return
        try:
            start = datetime.strptime(ng["start"], "%H:%M").time()
            end = datetime.strptime(ng["end"], "%H:%M").time()
        except Exception:
            log.error("صيغة وقت الحارس الليلي غير صالحة")
            return
        now_t = datetime.now().time()
        in_window = (start <= now_t or now_t < end) if start > end else (start <= now_t < end)
        if not in_window:
            return
        for intr in intruders:
            mac = intr.normalized_mac()
            if ng.get("auto_block"):
                self.devices.block_mac(mac)
                self.db.record_event("night_guard", "critical",
                                     f"الحارس الليلي حظر تلقائياً: {intr.hostname} ({mac})",
                                     mac=mac)
            else:
                self.db.record_event("night_guard", "critical",
                                     f"الحارس الليلي: جهاز غريب أثناء ساعات الحظر: "
                                     f"{intr.hostname} ({mac})", mac=mac)
            alert = Alert("الحارس الليلي",
                          f"جهاز غريب متصل أثناء ساعات الحظر ({ng['start']}–{ng['end']}):\n"
                          f"{intr.hostname or 'بدون اسم'} ({mac})",
                          "critical", mac=mac)
            self.alerts.notify(alert)
            if self.escalation:
                self.escalation.raise_critical(alert)

    def _maybe_daily_report(self) -> None:
        rep = self.cfg.get("reports", {})
        if not rep.get("daily_enabled"):
            return
        try:
            target = datetime.strptime(rep.get("daily_time", "23:59"), "%H:%M").time()
        except Exception:
            return
        marker = self.root / "data" / "last_daily_report.txt"
        today = date.today().isoformat()
        if marker.exists() and marker.read_text().strip() == today:
            return
        if datetime.now().time() >= target:
            from alerts.base import Alert
            summary = self.db.daily_summary(date.today())
            msg = self._format_daily(summary)
            self.alerts.notify(Alert("التقرير الأمني اليومي", msg, "info"))
            marker.write_text(today)
            log.info("أُرسل التقرير اليومي")

    @staticmethod
    def _format_daily(s: dict) -> str:
        sev = s.get("events_by_severity", {})
        return (
            f"ملخص اليوم:\n"
            f"- فحوصات: {s.get('scans', 0)}\n"
            f"- أجهزة جديدة: {s.get('new_devices', 0)}\n"
            f"- أحداث: {sum(sev.values())} "
            f"(حرجة {sev.get('critical', 0)}، تحذير {sev.get('warning', 0)})\n"
            f"- انقطاعات: {s.get('outages', 0)} "
            f"({s.get('outage_minutes', 0):.1f} دقيقة)\n"
            f"- متوسط السرعة: {s.get('avg_down') or '—'} Mbps"
        )

    # ---------- الحلقة المستمرة ----------

    def run_loop(self) -> None:
        """المراقبة المستمرة: جلسة متصفح واحدة تُعاد استخدامها عبر الفحوصات."""
        from core.browser import BrowserSession
        scan_cfg = self.cfg.get("scan", {})
        interval = int(scan_cfg.get("interval_seconds", 180))
        headless = bool(scan_cfg.get("headless", True))
        driver_path = scan_cfg.get("driver_path") or None
        log.info("بدء المراقبة المستمرة كل %d ثانية (جلسة متصفح مشتركة)",
                 interval)
        session = BrowserSession(headless=headless, driver_path=driver_path)
        try:
            while True:
                self.run_scan(driver_session=session)
                if self.escalation:
                    self.escalation.tick()
                log.info("الفحص القادم بعد %d ثانية", interval)
                time.sleep(interval)
        except KeyboardInterrupt:
            log.info("تم إيقاف المراقبة")
        finally:
            session.close()
            if self._telegram_bot:
                self._telegram_bot.stop()

    # ---------- الحالة للوحة التحكم ----------

    def get_status(self) -> dict:
        counts = {"total": 0, "allowed": 0, "visitor": 0, "unknown": 0, "blocked": 0,
                  "online": 0}
        for d in self.db.list_devices():
            counts["total"] += 1
            if d["status"] in counts:
                counts[d["status"]] += 1
            if d.get("present", 1) == 1:
                counts["online"] += 1
        last_scan = None
        last_scan_duration_ms = None
        try:
            last_scan = self.db.last_scan_at()
            last_scan_duration_ms = self.db.last_scan_duration_ms()
        except Exception:
            pass
        return {
            "router_ok": None,  # يُحدَّث بعد أول فحص ناجح
            "internet_ok": None,
            "last_scan": last_scan,
            "last_scan_duration_ms": last_scan_duration_ms,
            "counts": counts,
            "uptime_24h": self.internet.uptime_percent(24),
            "pending_escalations": len(self.escalation.pending_list())
            if self.escalation else 0,
        }

# ============================================================
# وحدة التحكم للوحة الويب
# ============================================================

class DashboardController:
    """يغلف RouterGuardApp بالواجهة التي تتوقعها dashboard/app.py."""

    def __init__(self, app: "RouterGuardApp"):
        self.app = app

    def get_status(self) -> dict:
        return self.app.get_status()

    def list_devices(self) -> list[dict]:
        return self.app.db.list_devices()

    def list_events(self, limit: int = 50) -> list[dict]:
        return self.app.db.list_events(limit=limit)

    def speed_history(self, hours: int = 24) -> list[dict]:
        since = datetime.now() - timedelta(hours=hours)
        return self.app.db.speed_history(since)

    def list_outages(self, hours: int = 24) -> list[dict]:
        since = datetime.now() - timedelta(hours=hours)
        return self.app.db.list_outages(since)

    def run_scan(self) -> dict:
        return self.app.run_scan()

    def block_device(self, mac: str) -> dict:
        ok = self.app.devices.block_mac(mac)
        return {"ok": ok,
                "message": f"تم حظر {mac}" if ok else "تعذر الحظر — تحقق من صيغة MAC"}

    def acknowledge_all(self) -> dict:
        if not self.app.escalation:
            return {"ok": True, "message": "لا يوجد نظام تصعيد مفعّل"}
        pending = self.app.escalation.pending_list()
        for p in pending:
            self.app.escalation.acknowledge(p["id"])
        return {"ok": True, "message": f"تم إقرار {len(pending)} تنبيهاً"}

    def daily_report(self) -> dict:
        return self.app.db.daily_summary(date.today())


# ============================================================
# الوضع التجريبي (demo) — فحص كامل ببيانات وهمية
# ============================================================

class _FakeDriver:
    def quit(self):
        pass


class _DemoRouterClient:
    """عميل وهمي يعيد أجهزة تجريبية: مسموحة + غريب + محظور."""

    def __init__(self, *args, **kwargs):
        pass

    def full_scan(self):
        rows = [
            DeviceRow(hostname="MyPhone", ip="192.168.1.5",
                      mac="8C:1F:5A:11:22:33",
                      raw="MyPhone | 192.168.1.5 | 8C:1F:5A:11:22:33"),
            DeviceRow(hostname="MyLaptop", ip="192.168.1.6",
                      mac="4C:72:B9:44:55:66",
                      raw="MyLaptop | 192.168.1.6 | 4C:72:B9:44:55:66"),
            DeviceRow(hostname="Unknown-Phone", ip="192.168.1.9",
                      mac="3C:06:30:AA:BB:CC",
                      raw="Unknown-Phone | 192.168.1.9 | 3C:06:30:AA:BB:CC"),
        ]
        return rows, ""


def run_demo(app: "RouterGuardApp") -> dict:
    """يشغّل فحصاً تجريبياً كاملاً: تنبيهات تُطبع في الكونسول."""
    from alerts.base import Alert, AlertPlugin

    class ConsoleAlert(AlertPlugin):
        name = "console"

        def send(self, alert: Alert) -> bool:
            print(f"\n[{alert.severity.upper()}] {alert.title}\n{alert.message}\n")
            return True

    app.alerts.register(ConsoleAlert())
    # عزل قائمة الحظر التجريبية عن الحقيقية
    app.devices.blocklist_path = app.devices.data_dir / "demo_blocklist.json"
    app.devices.blocklist_macs = app.devices._load_blocklist()
    # حظر مسبق لجهاز تجريبي لإظهار حالة BLOCKED
    app.devices.block_mac("DE:AD:BE:EF:00:01")

    import core.router_client as rc_mod
    real = rc_mod.RouterClient
    rc_mod.RouterClient = _DemoRouterClient
    try:
        result = app.run_scan(driver_factory=lambda: _FakeDriver())
    finally:
        rc_mod.RouterClient = real
    return result


# ============================================================
# أوامر CLI
# ============================================================

def cmd_init(args) -> int:
    root = project_root()
    src = root / "config.example.yaml"
    dst = root / "config.yaml"
    (root / "data").mkdir(exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    if dst.exists():
        print("config.yaml موجود مسبقاً — لم يتم استبداله.")
    else:
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print("تم إنشاء config.yaml — عدّل بيانات الراوتر والأجهزة المسموحة فيه.")
    print("تم تجهيز مجلدي data/ و logs/.")
    return 0


def cmd_scan(args) -> int:
    app = RouterGuardApp(args.config)
    res = app.run_scan()
    print(("نجح" if res["ok"] else "فشل") + ": " + res.get("message", ""))
    return 0 if res["ok"] else 1


def cmd_status(args) -> int:
    app = RouterGuardApp(args.config)
    st = app.get_status()
    c = st["counts"]
    print("=== حالة RouterGuard ===")
    print(f"آخر فحص: {st['last_scan'] or 'لم يتم بعد'}")
    print(f"الأجهزة: {c['total']} (مسموح {c['allowed']} | زائر {c['visitor']} | "
          f"غريب {c['unknown']} | محظور {c['blocked']})")
    print(f"Uptime آخر 24 ساعة: {st['uptime_24h']}%")
    print(f"تنبيهات معلقة: {st['pending_escalations']}")
    print("\nآخر 5 أحداث:")
    for e in app.db.list_events(limit=5):
        print(f"  [{e['severity']}] {e['at']} — {e['message'][:70]}")
    return 0


def cmd_devices(args) -> int:
    app = RouterGuardApp(args.config)
    devs = app.db.list_devices(status=args.status)
    if not devs:
        print("لا أجهزة مسجلة.")
        return 0
    from monitors.device_monitor import STATUS_AR
    print(f"{'الاسم':<22} {'MAC':<20} {'IP':<15} {'الحالة':<8} {'آخر ظهور'}")
    print("-" * 90)
    for d in devs:
        print(f"{(d['hostname'] or '?'):<22} {d['mac']:<20} "
              f"{(d['ip'] or '?'):<15} {STATUS_AR.get(d['status'], d['status']):<8} "
              f"{d['last_seen'] or ''}")
    return 0


def cmd_block(args) -> int:
    app = RouterGuardApp(args.config)
    ok = app.devices.block_mac(args.mac)
    print(f"تم حظر {args.mac}" if ok else "تعذر الحظر — تحقق من صيغة MAC")
    return 0 if ok else 1


def cmd_unblock(args) -> int:
    app = RouterGuardApp(args.config)
    ok = app.devices.unblock_mac(args.mac)
    print(f"تم إلغاء حظر {args.mac}" if ok else "الـ MAC غير محظور أصلاً")
    return 0 if ok else 1


def cmd_report(args) -> int:
    app = RouterGuardApp(args.config)
    day = date.fromisoformat(args.day) if args.day else date.today()
    s = app.db.daily_summary(day)
    print(f"=== التقرير اليومي {day} ===")
    print(RouterGuardApp._format_daily(s))
    from storage.reports import export_devices_csv, export_events_csv, render_html_report
    outdir = project_root() / "data" / "reports"
    outdir.mkdir(parents=True, exist_ok=True)
    export_devices_csv(app.db, str(outdir / f"devices_{day}.csv"))
    export_events_csv(app.db, str(outdir / f"events_{day}.csv"))
    html = outdir / f"report_{day}.html"
    render_html_report(app.db, day, str(html))
    print(f"صُدّر: {html}")
    if args.pdf:
        from storage.reports import export_pdf
        pdf = outdir / f"report_{day}.pdf"
        try:
            export_pdf(app.db, day, str(pdf))
            print(f"صُدّر: {pdf}")
        except RuntimeError as exc:
            print(exc)
    return 0


def cmd_dashboard(args) -> int:
    app = RouterGuardApp(args.config)
    from dashboard.app import create_app
    dash = app.cfg.get("dashboard", {})
    host = args.host or dash.get("host", "127.0.0.1")
    port = args.port or int(dash.get("port", 8080))
    flask_app = create_app(DashboardController(app))
    print(f"لوحة التحكم تعمل على http://{host}:{port}")
    flask_app.run(host=host, port=port, debug=False)
    return 0


def cmd_demo(args) -> int:
    import os
    # قاعدة بيانات تجريبية منفصلة — لا تلوث البيانات الحقيقية
    demo_db = project_root() / "data" / "demo.db"
    if demo_db.exists():
        demo_db.unlink()
    os.environ["ROUTERGUARD__STORAGE__PATH"] = "data/demo.db"
    app = RouterGuardApp(args.config)
    print("=== عرض تجريبي ببيانات وهمية ===")
    res = run_demo(app)
    print("النتيجة:", res.get("message"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RouterGuard — حارس الراوتر")
    p.add_argument("--config", default=None, help="مسار ملف الإعدادات")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="تهيئة أولى")
    sub.add_parser("run", help="تشغيل مستمر")
    sub.add_parser("scan", help="فحص واحد")
    sub.add_parser("status", help="ملخص الحالة")
    d = sub.add_parser("devices", help="قائمة الأجهزة")
    d.add_argument("--status", default=None,
                   choices=["allowed", "visitor", "unknown", "blocked"])
    b = sub.add_parser("block", help="حظر جهاز")
    b.add_argument("mac")
    u = sub.add_parser("unblock", help="إلغاء حظر")
    u.add_argument("mac")
    r = sub.add_parser("report", help="التقرير اليومي")
    r.add_argument("--day", default=None, help="YYYY-MM-DD")
    r.add_argument("--pdf", action="store_true", help="تصدير PDF أيضاً")
    dsh = sub.add_parser("dashboard", help="لوحة التحكم")
    dsh.add_argument("--host", default=None)
    dsh.add_argument("--port", type=int, default=None)
    sub.add_parser("demo", help="عرض تجريبي")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "run":
        RouterGuardApp(args.config).run_loop()
        return 0
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "devices":
        return cmd_devices(args)
    if args.command == "block":
        return cmd_block(args)
    if args.command == "unblock":
        return cmd_unblock(args)
    if args.command == "report":
        return cmd_report(args)
    if args.command == "dashboard":
        return cmd_dashboard(args)
    if args.command == "demo":
        return cmd_demo(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
