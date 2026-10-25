"""واجهة لوحة تحكم RouterGuard (Flask).

يعرّض هذا الوحدة دالة المصنع :func:`create_app` التي تبني تطبيق Flask
فوق كائن ``controller`` يملك الواجهة التالية فقط:

- ``get_status() -> dict``
- ``list_devices() -> list[dict]``
- ``list_events(limit: int) -> list[dict]``
- ``speed_history(hours: int) -> list[dict]``
- ``list_outages(hours: int) -> list[dict]``
- ``run_scan() -> dict`` يرجع ``{ok, message}``
- ``block_device(mac: str) -> dict`` يرجع ``{ok, message}``
- ``acknowledge_all() -> dict`` يرجع ``{ok, message}``
- ``daily_report() -> dict``

كل مسارات ``/api/*`` تُرجع JSON بصيغة ``{ok: bool, data/message}``
وأي استثناء يُحوَّل إلى 500 مع ``{ok: false, message}``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from flask import Flask, jsonify, render_template, request

logger = logging.getLogger("routerguard.dashboard")


def _ok(data: Any) -> Any:
    """ردّ JSON ناجح بصيغة موحّدة."""
    return jsonify({"ok": True, "data": data})


def _fail(message: str, status: int = 500) -> Any:
    """ردّ JSON فاشل بصيغة موحّدة."""
    return jsonify({"ok": False, "message": message}), status


def _safe(func: Callable[[], Any], action_name: str) -> Any:
    """تنفيذ دالة controller مع التقاط أي استثناء وتحويله لردّ 500."""
    try:
        return _ok(func())
    except Exception:  # noqa: BLE001 - أي خطأ من الطبقة الخلفية يصبح 500
        logger.exception("فشل أثناء تنفيذ: %s", action_name)
        return _fail(f"خطأ داخلي أثناء: {action_name}")


def create_app(controller: Any) -> Flask:
    """إنشاء تطبيق لوحة تحكم RouterGuard.

    Args:
        controller: كائن يطبّق واجهة الـ controller الموثّقة أعلاه.

    Returns:
        كائن Flask جاهز للتشغيل.
    """
    app = Flask(__name__)

    @app.get("/")
    def index():
        """الصفحة الرئيسية (HTML عربي RTL)."""
        try:
            return render_template("index.html")
        except Exception:
            logger.exception("فشل عرض الصفحة الرئيسية")
            return _fail("تعذّر عرض الصفحة الرئيسية")

    @app.get("/api/status")
    def api_status():
        """حالة الراوتر والإنترنت والعدّادات."""
        return _safe(controller.get_status, "جلب الحالة")

    @app.get("/api/devices")
    def api_devices():
        """قائمة الأجهزة المعروفة."""
        return _safe(controller.list_devices, "جلب الأجهزة")

    @app.get("/api/events")
    def api_events():
        """سجل الأحداث. يقبل ?limit= (الافتراضي 50)."""
        limit = request.args.get("limit", default=50, type=int) or 50
        return _safe(lambda: controller.list_events(limit), "جلب الأحداث")

    @app.get("/api/speed")
    def api_speed():
        """سجلّ السرعة. يقبل ?hours= (الافتراضي 24)."""
        hours = request.args.get("hours", default=24, type=int) or 24
        return _safe(lambda: controller.speed_history(hours), "جلب سجلّ السرعة")

    @app.get("/api/outages")
    def api_outages():
        """سجلّ الانقطاعات. يقبل ?hours= (الافتراضي 24)."""
        hours = request.args.get("hours", default=24, type=int) or 24
        return _safe(lambda: controller.list_outages(hours), "جلب الانقطاعات")

    @app.get("/api/report")
    def api_report():
        """التقرير اليومي."""
        return _safe(controller.daily_report, "جلب التقرير اليومي")

    @app.post("/api/scan")
    def api_scan():
        """تشغيل فحص يدوي للأجهزة المتصلة."""
        try:
            result = controller.run_scan()
        except Exception:
            logger.exception("فشل أثناء تشغيل الفحص")
            return _fail("خطأ داخلي أثناء تشغيل الفحص")
        if not isinstance(result, dict) or not result.get("ok"):
            message = result.get("message", "فشل الفحص") if isinstance(result, dict) else "فشل الفحص"
            logger.warning("الفحص أرجع فشلاً: %s", message)
            return jsonify({"ok": False, "message": message}), 200
        return jsonify({"ok": True, "message": result.get("message", "تم الفحص")})

    @app.post("/api/block")
    def api_block():
        """حظر جهاز. يتطلب JSON بصيغة {mac: "..."}."""
        payload = request.get_json(silent=True) or {}
        mac = (payload.get("mac") or "").strip()
        if not mac:
            return _fail("حقل mac مطلوب", status=400)
        try:
            result = controller.block_device(mac)
        except Exception:
            logger.exception("فشل أثناء حظر الجهاز %s", mac)
            return _fail(f"خطأ داخلي أثناء حظر {mac}")
        if not isinstance(result, dict) or not result.get("ok"):
            message = result.get("message", "فشل الحظر") if isinstance(result, dict) else "فشل الحظر"
            logger.warning("حظر %s أرجع فشلاً: %s", mac, message)
            return jsonify({"ok": False, "message": message}), 200
        return jsonify({"ok": True, "message": result.get("message", f"تم حظر {mac}")})

    @app.post("/api/ack")
    def api_ack():
        """إقرار كل التنبيهات المعلّقة."""
        try:
            result = controller.acknowledge_all()
        except Exception:
            logger.exception("فشل أثناء إقرار التنبيهات")
            return _fail("خطأ داخلي أثناء إقرار التنبيهات")
        if not isinstance(result, dict) or not result.get("ok"):
            message = result.get("message", "فشل الإقرار") if isinstance(result, dict) else "فشل الإقرار"
            logger.warning("الإقرار أرجع فشلاً: %s", message)
            return jsonify({"ok": False, "message": message}), 200
        return jsonify({"ok": True, "message": result.get("message", "تم إقرار التنبيهات")})

    return app
