import os
import logging
import json
import asyncio
import datetime as dt

# 🔴 لاگینگ باید همین اول، قبل از import هر ماژول دیگه‌ی پروژه، یک‌بار
# و فقط یک‌بار تنظیم بشه. قبلاً هم اینجا و هم داخل dispatcher.py صدا زده
# می‌شد (چون import شدن dispatcher قبل از این فراخوانی اتفاق می‌افتاد)
# که باعث دو مسیر لاگ موازی و گیج‌کننده می‌شد. الان فقط همین‌جاست.
from logging_config import setup_advanced_logging
setup_advanced_logging(
    log_dir="/var/log/sonar",
    level=logging.DEBUG,
    console_level=logging.INFO
)

from telegram.ext import ApplicationBuilder
from logger_setup import setup_logger
from dispatcher import register_all_handlers
import cronjobs
import bot_logic  # برای دسترسی به ارور هندلر و توکن

# راه‌اندازی هوک‌های کرش (crash hooks) - این تابع دیگه هندلر جدید نمی‌سازه،
# فقط excepthook و سطح لاگ کتابخانه‌های شلوغ (telegram/httpx/websockets) رو تنظیم می‌کنه
logger = setup_logger()

# خواندن تنظیمات (مسیر مطلق - مستقل از CWD هنگام اجرا با systemd)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'sonar_config.json')
try:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
        TOKEN = config.get('bot_token')
except Exception as e:
    logger.critical(f"❌ خواندن فایل کانفیگ ناموفق بود / Failed to read config file ({CONFIG_PATH}): {e}", exc_info=True)
    TOKEN = None

def main():
    if not TOKEN:
        print("⛔️ Error: Token not set.")
        return

    print("🚀 SONAR ULTRA PRO v4.3 RUNNING...")
    
    # 🔧 نسخه ۴.۲: pool_timeout و سقف صریح آپدیت‌های همزمان اضافه شد تا وقتی
    # چند کاربر همزمان کار سنگین می‌کنند، ارسال پیام‌ها پشت هم گیر نکند.
    async def _post_init(application):
        # 🩺 v4.3: ناظر تاخیر event loop — برای تشخیص اینکه هنگ از کد است یا از CPU سرور
        import runtime
        runtime.start_watchdog(threshold=1.0)

    async def _post_shutdown(application):
        try:
            from ws_client import GLOBAL_WS_POOL
            await GLOBAL_WS_POOL.close_all()
        except Exception:
            pass
        try:
            import runtime
            runtime.shutdown()
        except Exception:
            pass

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .pool_timeout(30.0)
        .connection_pool_size(256)
        .concurrent_updates(256)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    
    # اضافه کردن ارور هندلر از فایل لاجیک
    app.add_error_handler(bot_logic.error_handler)

    # ✅ ثبت تمام هندلرها از فایل دیسپچر
    # این خط حیاتی است: تمام دکمه‌ها و دستورات اینجا لود می‌شوند
    register_all_handlers(app)

    # راه‌اندازی جاب‌ها (Job Queue)
    if app.job_queue:
        app.job_queue.run_once(cronjobs.system_startup_notification, when=2)
        app.job_queue.run_once(cronjobs.startup_whitelist_job, when=15)
        app.job_queue.run_once(cronjobs.send_startup_topic_test, when=10)
        app.job_queue.run_daily(cronjobs.check_expiry_job, time=dt.time(hour=8, minute=30, second=0))
        app.job_queue.run_repeating(cronjobs.auto_scheduler_job, interval=120, first=30)
        app.job_queue.run_repeating(cronjobs.global_monitor_job, interval=60, first=10)
        app.job_queue.run_repeating(cronjobs.monitor_tunnels_job, interval=60, first=20)
        app.job_queue.run_repeating(cronjobs.auto_update_subs_job, interval=43200, first=3600)
        app.job_queue.run_repeating(cronjobs.auto_backup_send_job, interval=3600, first=300)
        app.job_queue.run_repeating(cronjobs.check_bonus_expiry_job, interval=43200, first=600)
    else:
        logger.error("JobQueue not available.")

    app.run_polling(
    drop_pending_updates=True, 
    close_loop=False,
    allowed_updates=None  # بند کردن آپدیت‌های اضافی
)
if __name__ == '__main__':
    main()