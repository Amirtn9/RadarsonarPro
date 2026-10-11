"""Owner-scoped printable A4 report. Install optional dependency: WeasyPrint.
Text is escaped and SQL never selects credentials/config links.
"""
from datetime import datetime, timezone
from html import escape
from pro_store import ProStore


def render_html(summary,rankings,incidents,owner):
    stamp=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    rows=''.join(f'<tr><td>{i}</td><td>{escape(str(r["name"])[:64])}</td><td>{escape(str(r["score"]))}</td><td>{escape(str(r["ping"]))}</td></tr>' for i,r in enumerate(rankings,1))
    alerts=''.join(f'<tr><td>{escape(str(r["severity"]))}</td><td>{escape(str(r["title"]))}</td><td>{escape(str(r["status"]))}</td></tr>' for r in incidents)
    return f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><style>
    @page{{size:A4;margin:16mm}}body{{font-family:"DejaVu Sans",sans-serif;color:#182334;font-size:11px;line-height:1.7}}
    h1{{font-size:24px;margin-bottom:2px}}h2{{font-size:16px;margin:24px 0 9px;border-bottom:2px solid #d5e4f5;padding-bottom:6px}}
    .sub{{color:#58708a}}.cards{{display:flex;gap:12px;margin:20px 0}}
    .card{{border:1px solid #cbdbee;background:#f3f8fc;border-radius:10px;padding:13px;flex:1}}
    .card strong{{display:block;font-size:22px;color:#214e78}}table{{width:100%;border-collapse:collapse;table-layout:fixed}}
    th,td{{border-bottom:1px solid #d8e3ed;padding:7px;text-align:right;word-wrap:break-word}}
    th{{background:#e7f0fb}}tr{{break-inside:avoid}}footer{{margin-top:24px;font-size:9px;color:#728397}}
    </style><body><h1>SONAR RADAR | گزارش مدیریتی</h1>
    <div class="sub">فضای کاری: {int(owner)} | تاریخ تولید: {escape(stamp)}</div>
    <div class="cards"><div class="card">سرور فعال<strong>{summary['servers']['active']} / {summary['servers']['total']}</strong></div>
    <div class="card">کانفیگ سالم<strong>{summary['configs']['healthy']} / {summary['configs']['total']}</strong></div>
    <div class="card">رخداد باز<strong>{summary['incidents']}</strong></div></div>
    <h2>رتبه‌بندی کانفیگ‌ها</h2><table><thead><tr><th>ردیف</th><th>عنوان</th><th>امتیاز /۱۰۰</th><th>پینگ ms</th></tr></thead><tbody>{rows or '<tr><td colspan="4">داده‌ای وجود ندارد</td></tr>'}</tbody></table>
    <h2>رخدادهای حل‌نشده</h2><table><thead><tr><th>اهمیت</th><th>رخداد</th><th>وضعیت</th></tr></thead><tbody>{alerts or '<tr><td colspan="3">رخداد حل‌نشده‌ای وجود ندارد</td></tr>'}</tbody></table>
    <footer>این گزارش بر اساس آخرین داده ثبت‌شده است و جایگزین بررسی لحظه‌ای و تشخیص قطعی علت اختلال نیست.</footer></body></html>'''


def generate_pdf(actor,owner=None):
    from weasyprint import HTML
    store=ProStore();owner=store.workspace(actor,owner)
    summary=store.summary(actor,owner)
    rankings=store.rankings(actor,owner,20)
    incidents=store.incidents(actor,owner,'unresolved',20)
    page=render_html(summary,rankings,incidents,owner)
    return HTML(string=page,base_url=None).write_pdf()
