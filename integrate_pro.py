from pathlib import Path
p=Path(__file__).resolve().parent

def change(file,old,new,once=True):
    f=p/file;s=f.read_text(encoding='utf-8');n=s.count(old)
    if not n:raise RuntimeError(f'Not found {file}: {old[:80]}')
    if once and n!=1:raise RuntimeError(f'Nonunique pattern ({n}) {file}')
    f.write_text(s.replace(old,new,1 if once else -1),encoding='utf-8')

# Schema created atomically at first deployment even if run standalone app bot.
change('bot.py',"        runtime.start_watchdog(threshold=1.0)","""        runtime.start_watchdog(threshold=1.0)
        # Pro schema migrations fail startup rather than leaving half-working controls.
        from pro_store import install_schema
        await asyncio.to_thread(install_schema)""")
change('bot.py',"        app.job_queue.run_repeating(cronjobs.check_bonus_expiry_job, interval=43200, first=600)","""        app.job_queue.run_repeating(cronjobs.check_bonus_expiry_job, interval=43200, first=600)
        from pro_jobs import multi_probe_job, digest_job, cleanup_job
        app.job_queue.run_repeating(multi_probe_job, interval=1800, first=300,
                                    job_kwargs={'max_instances': 1, 'coalesce': True})
        app.job_queue.run_repeating(digest_job, interval=3600, first=360,
                                    job_kwargs={'max_instances': 1, 'coalesce': True})
        app.job_queue.run_daily(cleanup_job, time=dt.time(hour=3, minute=0))""")
# Both callback route + text commands registered in the existing singleton dispatcher
change('dispatcher.py',"    logger.debug(\"📝 Starting handler registration...\")", """    logger.debug("📝 Starting handler registration...")
    from pro_handlers import register as register_pro_handlers
    register_pro_handlers(app)""")
# hook optional WebApp control into main menu, only when HTTPS URL explicit
change('keyboard.py',"from settings import SUBSCRIPTION_PLANS","""from settings import SUBSCRIPTION_PLANS
from telegram import WebAppInfo
from urllib.parse import urlparse
import os

def _webapp_button():
    url=os.getenv('SONAR_WEBAPP_URL','').strip()
    parsed=urlparse(url)
    if parsed.scheme=='https' and parsed.hostname:
        return InlineKeyboardButton('📱 پنل گرافیکی',web_app=WebAppInfo(url=url))
    return None""")
change('keyboard.py',"        [InlineKeyboardButton(\"📊 داشبورد شبکه\", callback_data='status_dashboard')],", """        [InlineKeyboardButton('📊 مرکز حرفه‌ای سونار', callback_data='pro_home')],
        [InlineKeyboardButton("📊 داشبورد شبکه", callback_data='status_dashboard')],""")
change('keyboard.py',"    if user_id == admin_id:\n        kb.insert(0, [InlineKeyboardButton(\"🤖 مدیریت ربات\", callback_data='admin_panel_main')])", """    webapp=_webapp_button()
    if webapp:kb.insert(1,[webapp])
    if user_id == admin_id:
        kb.insert(0, [InlineKeyboardButton("🤖 مدیریت ربات", callback_data='admin_panel_main')])""")
change('keyboard.py',"[InlineKeyboardButton(\"🔑 دریافت توکن پنل وب\", callback_data='gen_web_token')],\n        [InlineKeyboardButton(\"➕ افزایش موجودی (به زودی)\", callback_data='top_up_wallet')], # دکمه نمایشی برای آینده", """[InlineKeyboardButton('📱 راه‌اندازی پنل گرافیکی', callback_data='gen_web_token')],
        [InlineKeyboardButton('📊 مرکز حرفه‌ای', callback_data='pro_home')],""")
change('keyboard.py',"[InlineKeyboardButton(\"🔑 دریافت توکن پنل وب (Web Token)\", callback_data='gen_web_token')],", "[InlineKeyboardButton('📱 پنل گرافیکی', callback_data='gen_web_token')],")
change('keyboard.py',"        [InlineKeyboardButton(\"🔙 منوی اصلی\", callback_data='main_menu')]\n    ]\n    return InlineKeyboardMarkup(kb)\n\ndef server_stats_kb():", """        [InlineKeyboardButton('📡 مرکز حرفه‌ای سونار', callback_data='pro_home')],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(kb)

def server_stats_kb():""")
# remove duplicate config_cron_kb definitions: keep most recent version
import ast
kf=p/'keyboard.py';s=kf.read_text();tree=ast.parse(s);dupes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='config_cron_kb']
if len(dupes)>1:
    lines=s.splitlines(keepends=True)
    for n in sorted(dupes[:-1],key=lambda x:x.lineno,reverse=True):
        del lines[n.lineno-1:n.end_lineno]
    kf.write_text(''.join(lines),encoding='utf-8')

# Replace no-op web token action with optional HTTPS Mini App button.
change('bot_logic_mod/menu.py',"""async def web_token_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.callback_query.answer("🚧 پنل تحت وب در حال توسعه است.\\nبه زودی این قابلیت فعال می‌شود!", show_alert=True)
    except: pass""", """async def web_token_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from keyboard import _webapp_button
    btn = _webapp_button()
    if btn:
        markup = InlineKeyboardMarkup([[btn], [InlineKeyboardButton('🔙 بازگشت',callback_data='main_menu')]])
        await safe_edit_message(update, '📱 **پنل گرافیکی Sonar Radar**\\nبا دکمه زیر وارد پنل شوید. ورود تنها با امضای معتبر تلگرام مجاز است.',reply_markup=markup)
    else:
        await safe_edit_message(update, '📱 **پنل گرافیکی آماده نصب است.**\\nمدیر سرور باید Web API را با HTTPS فعال کند و متغیر SONAR_WEBAPP_URL را تنظیم کند.\\nتوکن ساده یا لینک ورود بدون احراز هویت صادر نمی‌شود.',reply_markup=keyboard.back_btn())""")

# Monitor server events -> correlated incident history (without blocking loop)
change('cronjobs.py',"""            if fail_count >= DOWN_RETRY_LIMIT:
                if fail_count == DOWN_RETRY_LIMIT:   # فقط بار اول پیام بده""", """            if fail_count >= DOWN_RETRY_LIMIT:
                if fail_count == DOWN_RETRY_LIMIT:
                    try:
                        from pro_store import ProStore
                        await asyncio.to_thread(ProStore().incident, srv['owner_id'], 'server', sid,
                                                'server_down', f'قطع ارتباط با سرور {name}', 'critical', True)
                    except Exception:logger.exception('Pro incident persistence failed')
                if fail_count == DOWN_RETRY_LIMIT:   # فقط بار اول پیام بده""")
change('cronjobs.py',"""            if SERVER_FAILURE_COUNTS.get(sid, 0) > 0:
                SERVER_FAILURE_COUNTS[sid] = 0""", """            if SERVER_FAILURE_COUNTS.get(sid, 0) > 0:
                SERVER_FAILURE_COUNTS[sid] = 0
                try:
                    from pro_store import ProStore
                    await asyncio.to_thread(ProStore().incident, srv['owner_id'], 'server',sid,
                                            'server_down', f'بازیابی سرور {name}', 'critical',False)
                except Exception:logger.exception('Pro incident resolution failed')""")

# Settings center hyperlink
change('cronjob_hub.py',"""        [InlineKeyboardButton("📊 گزارش دوره‌ای سرورها", callback_data="settings_cron")],""", """        [InlineKeyboardButton('🚨 مرکز رخدادها و هشدارهای پیشرفته',callback_data='pro_prefs')],
        [InlineKeyboardButton("📊 گزارش دوره‌ای سرورها", callback_data="settings_cron")],""")

print('Integrated Pro 5 into existing codebase')
