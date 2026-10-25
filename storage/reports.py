"""التقارير: CSV (مع BOM للعربية)، HTML عربي RTL، وPDF عبر reportlab."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .database import Database


def export_devices_csv(db: Database, path: str | Path) -> Path:
    """تصدير الأجهزة إلى CSV مع BOM لدعم العربية في Excel."""
    path = Path(path)
    rows = db.list_devices()
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id", "mac", "hostname", "ip", "status",
                "first_seen", "last_seen", "vendor",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def export_events_csv(db: Database, path: str | Path) -> Path:
    """تصدير الأحداث إلى CSV مع BOM."""
    path = Path(path)
    rows = db.list_events(limit=100000)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "at", "type", "severity", "message", "mac", "extra"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def render_html_report(db: Database, day: date, out_path: str | Path) -> Path:
    """تقرير HTML عربي RTL أنيق لملخص اليوم. CSS مضمّن."""
    out_path = Path(out_path)
    summary = db.daily_summary(day)
    devices = db.list_devices()
    events = db.list_events(limit=50)

    def sev_row(sev: str, count: int) -> str:
        color = {"critical": "#c0392b", "warning": "#e67e22"}.get(sev, "#2c3e50")
        return (
            f"<tr><td style='color:{color};font-weight:bold'>{sev}</td>"
            f"<td>{count}</td></tr>"
        )

    events_rows = "".join(sev_row(s, c) for s, c in summary["events_by_severity"].items())
    devices_rows = "".join(
        f"<tr><td>{d['mac']}</td><td>{d['hostname']}</td><td>{d['ip']}</td>"
        f"<td>{d['status']}</td><td>{d['vendor']}</td></tr>"
        for d in devices
    )
    events_list = "".join(
        f"<li><b>{e['at'][:16]}</b> [{e['severity']}] {e['message']}</li>"
        for e in events
    )

    html_doc = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<title>تقرير RouterGuard — {summary['day']}</title>
<style>
body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background:#f5f7fa; color:#2c3e50; margin:0; padding:20px; }}
.container {{ max-width:900px; margin:auto; background:#fff; border-radius:12px; padding:30px; box-shadow:0 2px 8px rgba(0,0,0,.08); }}
h1 {{ color:#1a5276; border-bottom:3px solid #2980b9; padding-bottom:10px; }}
h2 {{ color:#2e86c1; margin-top:30px; }}
.cards {{ display:flex; gap:15px; flex-wrap:wrap; }}
.card {{ flex:1; min-width:140px; background:#eaf2f8; border-radius:10px; padding:15px; text-align:center; }}
.card .num {{ font-size:28px; font-weight:bold; color:#1a5276; }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
th, td {{ border:1px solid #d6e4f0; padding:8px; text-align:right; }}
th {{ background:#2980b9; color:#fff; }}
ul {{ line-height:1.9; }}
.footer {{ margin-top:30px; color:#888; font-size:12px; text-align:center; }}
</style>
</head>
<body>
<div class="container">
<h1>🛡️ تقرير RouterGuard — {summary['day']}</h1>
<h2>📊 الملخص</h2>
<div class="cards">
<div class="card"><div class="num">{summary['new_devices']}</div><div>أجهزة جديدة</div></div>
<div class="card"><div class="num">{summary['outages']}</div><div>انقطاعات ({summary['outage_minutes']} دقيقة)</div></div>
<div class="card"><div class="num">{summary['avg_down'] if summary['avg_down'] is not None else '—'}</div><div>متوسط التحميل (Mbps)</div></div>
<div class="card"><div class="num">{summary['scans']}</div><div>فحوصات</div></div>
</div>
<h2>🚦 الأحداث حسب الخطورة</h2>
<table><tr><th>الخطورة</th><th>العدد</th></tr>{events_rows or '<tr><td colspan="2">لا أحداث</td></tr>'}</table>
<h2>💻 الأجهزة ({len(devices)})</h2>
<table><tr><th>MAC</th><th>الاسم</th><th>IP</th><th>الحالة</th><th>الشركة</th></tr>{devices_rows or '<tr><td colspan="5">لا أجهزة</td></tr>'}</table>
<h2>📝 آخر الأحداث</h2>
<ul>{events_list or '<li>لا أحداث</li>'}</ul>
<div class="footer">RouterGuard — تقرير تلقائي</div>
</div>
</body>
</html>"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def export_pdf(db: Database, day: date, out_path: str | Path) -> Path:
    """تصدير ملخص اليوم إلى PDF عبر reportlab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError(
            "مكتبة reportlab غير مثبتة — ثبّتها بـ: pip install reportlab"
        ) from exc

    out_path = Path(out_path)
    summary = db.daily_summary(day)
    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    y = height - 60
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, y, f"RouterGuard Daily Report - {summary['day']}")
    y -= 30
    c.setFont("Helvetica", 12)
    lines = [
        f"New devices: {summary['new_devices']}",
        f"Outages: {summary['outages']} ({summary['outage_minutes']} min)",
        f"Avg download: {summary['avg_down']} Mbps",
        f"Scans: {summary['scans']}",
        f"Events by severity: {summary['events_by_severity']}",
    ]
    for line in lines:
        c.drawString(60, y, line)
        y -= 20
    c.save()
    return out_path
