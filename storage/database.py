"""قاعدة بيانات SQLite لتخزين الفحوصات والأجهزة والأحداث والسرعة والانقطاعات."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import date, datetime
from functools import wraps
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.types import DeviceRow  # noqa: E402


def _iso(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _locked(method):
    """يضمن أن عمليات قاعدة البيانات لا تتداخل بين threads (لوحة الويب)."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Database:
    """واجهة SQLite: تُنشأ الجداول في الباني، وتُخزَّن التواريخ بصيغة ISO."""

    def __init__(self, path: str, logger: logging.Logger | None = None) -> None:
        self._path = Path(path)
        self._logger = logger or logging.getLogger("routerguard.storage")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        try:
            self._conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.Error:  # noqa: BLE001 - WAL اختياري
            self._logger.debug("تعذّر تفعيل WAL", exc_info=True)

    # ---- البنية ----

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                device_count INT NOT NULL DEFAULT 0,
                intruder_count INT NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac TEXT UNIQUE NOT NULL,
                hostname TEXT NOT NULL DEFAULT '',
                ip TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                vendor TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_devices_mac ON devices(mac);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                mac TEXT,
                extra TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);
            CREATE TABLE IF NOT EXISTS speed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                down_mbps REAL,
                up_mbps REAL,
                ping_ms REAL
            );
            CREATE TABLE IF NOT EXISTS outages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                duration_sec INT NOT NULL
            );
            """
        )
        self._conn.commit()
        # ترحيل آمن لقواعد البيانات الموجودة مسبقاً: أعمدة جديدة بقيم افتراضية
        for stmt in (
            "ALTER TABLE devices ADD COLUMN present INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE scans ADD COLUMN duration_ms INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # العمود موجود مسبقاً — لا حاجة للترحيل
        self._conn.commit()

    @_locked
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- الفحوصات ----

    @_locked
    def record_scan(
        self,
        at: datetime | str,
        rows: list[DeviceRow],
        intruder_count: int,
        error: str = "",
        duration_ms: int = 0,
    ) -> int:
        """تسجيل فحص واحد. يعيد id السجل."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO scans (at, device_count, intruder_count, error, duration_ms)"
                " VALUES (?, ?, ?, ?, ?)",
                (_iso(at), len(rows), intruder_count, error, int(duration_ms)),
            )
            return cur.lastrowid

    # ---- الأجهزة ----

    @_locked
    def upsert_device(
        self, mac: str, hostname: str, ip: str, status: str
    ) -> tuple[int, bool]:
        """إدراج أو تحديث جهاز. يعيد (id, is_new). يعيد present=1 دائماً."""
        now = datetime.now().isoformat()
        with self._conn:
            row = self._conn.execute(
                "SELECT id FROM devices WHERE mac = ?", (mac,)
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE devices SET hostname=?, ip=?, status=?, last_seen=?,"
                    " present=1 WHERE mac=?",
                    (hostname, ip, status, now, mac),
                )
                return row["id"], False
            cur = self._conn.execute(
                "INSERT INTO devices (mac, hostname, ip, status, first_seen, last_seen,"
                " present) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (mac, hostname, ip, status, now, now),
            )
            return cur.lastrowid, True

    @_locked
    def mark_device_left(self, mac: str, at: datetime | str) -> None:
        """يعلّم جهازاً بأنه غادر الشبكة (present=0) مع الاحتفاظ بآخر ظهور."""
        with self._conn:
            self._conn.execute(
                "UPDATE devices SET present=0 WHERE mac=? AND present=1", (mac,)
            )

    @_locked
    def touch_seen(self, mac: str, at: datetime | str) -> None:
        """تحديث آخر ظهور لجهاز."""
        with self._conn:
            self._conn.execute(
                "UPDATE devices SET last_seen=? WHERE mac=?", (_iso(at), mac)
            )

    @_locked
    def update_device_status(self, mac: str, status: str) -> None:
        """تحديث حالة جهاز (trusted/intruder/blocked/...)."""
        with self._conn:
            self._conn.execute(
                "UPDATE devices SET status=? WHERE mac=?", (status, mac)
            )

    @_locked
    def set_vendor(self, mac: str, vendor: str) -> None:
        """تحديث عمود vendor لجهاز موجود."""
        with self._conn:
            self._conn.execute(
                "UPDATE devices SET vendor=? WHERE mac=?", (vendor, mac)
            )

    @_locked
    def get_device(self, mac: str) -> dict | None:
        """جلب جهاز واحد كـ dict أو None."""
        row = self._conn.execute(
            "SELECT * FROM devices WHERE mac = ?", (mac,)
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def list_devices(self, status: str | None = None) -> list[dict]:
        """قائمة الأجهزة، مع فلترة اختيارية بالحالة."""
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM devices ORDER BY last_seen DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM devices WHERE status=? ORDER BY last_seen DESC",
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- الأحداث ----

    @_locked
    def record_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        mac: str | None = None,
        extra: dict | None = None,
        at: datetime | str | None = None,
    ) -> int:
        """تسجيل حدث. يعيد id."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO events (at, type, severity, message, mac, extra)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _iso(at or datetime.now()),
                    event_type,
                    severity,
                    message,
                    mac,
                    json.dumps(extra or {}, ensure_ascii=False),
                ),
            )
            return cur.lastrowid

    @_locked
    def list_events(
        self, limit: int = 100, since: datetime | str | None = None
    ) -> list[dict]:
        """أحدث الأحداث تنازلياً، مع فلترة اختيارية بـ since."""
        if since is None:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE at >= ? ORDER BY id DESC LIMIT ?",
                (_iso(since), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- السرعة ----

    @_locked
    def record_speed(
        self, at: datetime | str, down: float, up: float, ping: float
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO speed (at, down_mbps, up_mbps, ping_ms)"
                " VALUES (?, ?, ?, ?)",
                (_iso(at), down, up, ping),
            )

    @_locked
    def speed_history(self, since: datetime | str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM speed WHERE at >= ? ORDER BY at ASC", (_iso(since),)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- الانقطاعات ----

    @_locked
    def record_outage(self, started: datetime, ended: datetime) -> int:
        """تسجيل انقطاع وحساب مدته بالثواني. يعيد id."""
        duration = max(0, int((ended - started).total_seconds()))
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO outages (started_at, ended_at, duration_sec)"
                " VALUES (?, ?, ?)",
                (started.isoformat(), ended.isoformat(), duration),
            )
            return cur.lastrowid

    @_locked
    def list_outages(self, since: datetime | str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM outages WHERE started_at >= ? ORDER BY started_at ASC",
            (_iso(since),),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- الصيانة ----

    @_locked
    @_locked
    def last_scan_at(self) -> str | None:
        """وقت آخر فحص مسجل (بصيغة ISO) أو None."""
        row = self._conn.execute(
            "SELECT at FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else None

    @_locked
    def last_scan_duration_ms(self) -> int | None:
        """مدة آخر فحص بالمللي ثانية أو None."""
        row = self._conn.execute(
            "SELECT duration_ms FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        return int(row[0]) if row else None

    def prune(self, retention_days: int) -> dict:
        """حذف السجلات الأقدم من retention_days. يعيد الأعداد المحذوفة."""
        cutoff = (datetime.now().timestamp() - retention_days * 86400)
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()
        counts: dict[str, int] = {}
        with self._conn:
            for table, col in (
                ("scans", "at"),
                ("events", "at"),
                ("speed", "at"),
                ("outages", "started_at"),
            ):
                cur = self._conn.execute(
                    f"DELETE FROM {table} WHERE {col} < ?", (cutoff_iso,)
                )
                counts[table] = cur.rowcount
        self._logger.info("prune حذف: %s", counts)
        return counts

    # ---- الملخص اليومي ----

    @_locked
    def daily_summary(self, day: date) -> dict:
        """ملخص يوم: أجهزة جديدة، أحداث حسب الخطورة، انقطاعات، متوسط السرعة، فحوصات."""
        start = datetime(day.year, day.month, day.day).isoformat()
        end = datetime(day.year, day.month, day.day, 23, 59, 59).isoformat()

        new_devices = self._conn.execute(
            "SELECT COUNT(*) c FROM devices WHERE first_seen BETWEEN ? AND ?",
            (start, end),
        ).fetchone()["c"]

        events_by_severity: dict[str, int] = {}
        for row in self._conn.execute(
            "SELECT severity, COUNT(*) c FROM events"
            " WHERE at BETWEEN ? AND ? GROUP BY severity",
            (start, end),
        ):
            events_by_severity[row["severity"]] = row["c"]

        outage_rows = self._conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(duration_sec), 0) s FROM outages"
            " WHERE started_at BETWEEN ? AND ?",
            (start, end),
        ).fetchone()

        avg_down = self._conn.execute(
            "SELECT AVG(down_mbps) a FROM speed WHERE at BETWEEN ? AND ?",
            (start, end),
        ).fetchone()["a"]

        scans = self._conn.execute(
            "SELECT COUNT(*) c FROM scans WHERE at BETWEEN ? AND ?", (start, end)
        ).fetchone()["c"]

        return {
            "day": day.isoformat(),
            "new_devices": new_devices,
            "events_by_severity": events_by_severity,
            "outages": outage_rows["c"],
            "outage_minutes": round(outage_rows["s"] / 60, 1),
            "avg_down": round(avg_down, 2) if avg_down is not None else None,
            "scans": scans,
        }
