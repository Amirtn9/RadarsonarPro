import asyncio
import io
import requests
from runtime import SHARED_EXECUTOR  # 🔧 v4.2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import keyboard
from database import Database

# اتصال به دیتابیس
db = Database()

# تعریف استیت برای ConversationHandler
GET_GROUP_ID_FOR_TOPICS = 400

async def setup_group_notify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرحله ۱: نمایش راهنما به کاربر"""
    txt = (
        "📢 **راه‌اندازی سیستم اطلاع‌رسانی پیشرفته (Topics)**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "در این قابلیت، ربات به صورت خودکار در گروه شما تاپیک‌های جداگانه می‌سازد:\n"
        "🚨 تاپیک هشدارها\n"
        "📊 تاپیک گزارشات\n"
        "⏳ تاپیک انقضا\n\n"
        "⚠️ **مراحل الزامی قبل از ادامه:**\n"
        "1️⃣ یک گروه بسازید.\n"
        "2️⃣ قابلیت **Topics** را در تنظیمات گروه روشن کنید.\n"
        "3️⃣ ربات را به گروه اضافه کرده و **Admin** کنید (دسترسی کامل).\n"
        "4️⃣ آیدی عددی گروه را پیدا کنید (از ربات `@username_to_id_bot` کمک بگیرید)."
    )
    kb = [
        [InlineKeyboardButton("✅ انجام دادم، مرحله بعد", callback_data='get_group_id_step')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='channels_menu')]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def get_group_id_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرحله ۲: دریافت آیدی گروه"""
    await update.callback_query.answer()
    txt = (
        "🔢 **لطفاً آیدی عددی گروه را ارسال کنید:**\n\n"
        "مثال: `-1001234567890`\n"
        "⚠️ حتماً با -100 شروع می‌شود."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=keyboard.get_cancel_markup(), parse_mode='Markdown')
    return GET_GROUP_ID_FOR_TOPICS

async def set_group_photo(context, group_id):
    """تابع کمکی برای تغییر عکس پروفایل گروه"""
    PHOTO_URL = "https://raw.githubusercontent.com/Amirtn9/Radar-Sonar/main/sonar-radar-logo.png"
    try:
        # دانلود عکس (در ترد جداگانه)
        def _dl():
            return requests.get(PHOTO_URL, timeout=15)

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(SHARED_EXECUTOR, _dl)  # 🔧 v4.2

        if response.status_code == 200:
            bio = io.BytesIO(response.content)
            bio.name = "sonar_group_logo.png"
            await context.bot.set_chat_photo(chat_id=int(group_id), photo=bio)
            return True, "✅ پروفایل گروه آپدیت شد."
        return False, "❌ دانلود عکس لوگو ناموفق بود."
    except Exception as e:
        return False, f"⚠️ تغییر پروفایل انجام نشد: {str(e)[:50]}"

async def perform_group_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مرحله ۳: ساخت خودکار تاپیک‌ها، ذخیره در دیتابیس و تغییر پروفایل"""
    group_id = update.message.text.strip()
    uid = update.effective_user.id
    
    if not group_id.startswith("-100"):
        await update.message.reply_text("❌ آیدی گروه نامعتبر است. باید با -100 شروع شود.")
        return GET_GROUP_ID_FOR_TOPICS

    status_msg = await update.message.reply_text(
        "⏳ **در حال پیکربندی گروه و ساخت تاپیک‌ها...**",
        parse_mode='Markdown'
    )
    
    # لیست تاپیک‌های حرفه‌ای طبق درخواست
    topics_to_create = [
        ("📢 جنرال و همگانی", "all", None),                # جنرال
        ("🚨 هشدار قطع/وصل سرور", "down", None),           # هشدار سرور
        ("🔥 وضعیت منابع", "resource", None),              # هشدار منابع
        ("⏳ انقضا و تمدید", "expiry", None),              # هشدار انقضا
        ("📊 گزارشات سرورها", "report", None),             # گزارش سرور
        ("📡 وضعیت کانفیگ‌ها", "config_report", None),     # گزارش کانفیگ
        ("❌ هشدار قطعی کانفیگ", "config_alert", None)     # هشدار کانفیگ
    ]
    
    created_log = ""
    
    try:
        # 1. پاکسازی کانال‌های قبلی
        with db.get_connection() as (conn, cur):
            cur.execute("DELETE FROM channels WHERE owner_id = %s", (uid,))
            conn.commit()

        # 2. ساخت تاپیک‌ها
        for name, usage, icon_color in topics_to_create:
            try:
                topic = await context.bot.create_forum_topic(
                    chat_id=int(group_id),
                    name=name,
                    icon_color=None
                )
                db.add_channel(uid, group_id, f"Group | {name}", usage, topic.message_thread_id)
                created_log += f"✅ تاپیک **{name}** ساخته شد.\n"
                await asyncio.sleep(1.5) # جلوگیری از لیمیت تلگرام
                
            except Exception as e:
                created_log += f"❌ خطا در ساخت {name}: {e}\n"

        # 3. تغییر عکس پروفایل گروه
        photo_ok, photo_msg = await set_group_photo(context, group_id)
        created_log += f"\n🖼 {photo_msg}"

        await status_msg.edit_text(
            f"🎉 **عملیات با موفقیت پایان یافت!**\n\n"
            f"{created_log}\n\n"
            f"از این پس تمام اعلان‌ها با نظم کامل در تاپیک‌های مربوطه ارسال می‌شوند."
        ,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await status_msg.edit_text(
            f"❌ **خطای کلی:**\n{e}\n\nآیا مطمئنید تاپیک‌ها در گروه روشن است و ربات ادمین است؟",
            parse_mode='Markdown'
        )

    return ConversationHandler.END