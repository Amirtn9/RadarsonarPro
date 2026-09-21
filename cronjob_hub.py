# -*- coding: utf-8 -*-
"""
==============================================================================
🗓️ SONAR RADAR - UNIFIED CRONJOB HUB (v1.1 - نسخه ۴.۱)
==============================================================================
یک دکمهٔ واحد «🗓 مرکز کرون‌جاب‌ها» که همه‌چیز مربوط به زمان‌بندی را در یک
مسیر روشن جمع می‌کند، تا کاربر مجبور نباشد بین چند زیرمنوی پراکنده بگردد.
این ماژول چیزی را از نو نمی‌سازد - فقط یک لایه‌ی «فهرست» روی صفحات
زمان‌بندی‌ای که از قبل در keyboard.py/bot_logic هست قرار می‌دهد.

تغییرات نسخه ۴.۱:
- بخش «آپدیت خودکار سابسکریپشن‌ها» حذف شد: به ماژول subscription_scheduler.py
  وابسته بود که هیچ‌وقت ساخته نشد و باعث ImportError می‌شد. اگر در آینده این
  فیچر ساخته شد، دوباره اضافه‌اش کن.
- ایمپورت شکسته `from logger_setup import get_logger` (تابعی که دیگر در
  logger_setup.py وجود ندارد) با الگوی استاندارد لاگینگ پروژه جایگزین شد.
- این فایل الان واقعاً در dispatcher.py رجیستر شده (قبلاً ساخته شده بود
  ولی هیچ‌جا وصل نبود و دکمه‌اش بی‌جواب می‌ماند).

ساختار نهایی که کاربر می‌بیند:

    🗓 مرکز کرون‌جاب‌ها
    ├── 📊 گزارش دوره‌ای سرورها          → settings_cron
    ├── 📡 گزارش دوره‌ای کانفیگ‌ها        → settings_conf_cron
    ├── 🔄 آپدیت خودکار مخازن سیستم       → auto_up_menu
    ├── ⚠️ ریبوت خودکار سرورها            → auto_reboot_menu
    ├── 🎚 هشدارها و آستانه منابع         → menu_schedules
    └── 🔙 بازگشت
==============================================================================
"""

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def cronjob_hub_kb():
    """منوی اصلی مرکز کرون‌جاب‌ها - نقطه ورود واحد کاربر"""
    kb = [
        [InlineKeyboardButton("🗓 مرکز کرون‌جاب‌ها", callback_data="header_none")],

        [InlineKeyboardButton("📊 گزارش دوره‌ای سرورها", callback_data="settings_cron")],
        [InlineKeyboardButton("📡 گزارش دوره‌ای کانفیگ‌ها", callback_data="settings_conf_cron")],
        [InlineKeyboardButton("🔄 آپدیت خودکار مخازن سیستم", callback_data="auto_up_menu")],
        [InlineKeyboardButton("⚠️ ریبوت خودکار سرورها", callback_data="auto_reboot_menu")],
        [InlineKeyboardButton("🎚 هشدارها و آستانه منابع", callback_data="menu_schedules")],

        [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="settings_menu")],
    ]
    return InlineKeyboardMarkup(kb)


async def open_cronjob_hub(update, context: ContextTypes.DEFAULT_TYPE):
    """کالبک: cronjob_hub_main"""
    query = update.callback_query
    await query.answer()
    txt = (
        "🗓 <b>مرکز کرون‌جاب‌ها</b>\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "همه چیز مربوط به زمان‌بندی و آپدیت‌های خودکار اینجاست:\n\n"
        "📊 گزارش دوره‌ای وضعیت سرورها به کانال\n"
        "📡 گزارش دوره‌ای وضعیت کانفیگ‌ها\n"
        "🔄 آپدیت خودکار مخازن سیستم سرورها\n"
        "⚠️ ریبوت خودکار در صورت قطعی مکرر\n"
        "🎚 آستانه هشدار مصرف منابع (CPU/RAM/Disk)"
    )
    try:
        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=cronjob_hub_kb())
    except Exception as e:
        logger.error(f"باز کردن مرکز کرون‌جاب ناموفق بود / failed to open cronjob hub: {e}", exc_info=True)
