"""Admin Panel Handlers for Sonar Radar Ultra Pro. 

This module handles all admin-related operations including:
- User management (create, ban, delete, upgrade)
- Server monitoring and reporting
- Payment settings
- Database backups
- Broadcasting messages
"""

import logging
import asyncio
import os
import json
from datetime import datetime, timedelta
import jdatetime
from concurrent.futures import ThreadPoolExecutor

# --- Telegram Imports ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# --- Local Modules ---
import keyboard
from states import *
from database import Database
from settings import SUPER_ADMIN_ID, KEY_FILE, AGENT_PORT
from ws_client import reconnect_all as ws_reconnect_all
from core import ServerMonitor, get_jalali_str, get_tehran_datetime, sec
from server_stats import StatsManager
from scoring import ScoreEngine
from cryptography.fernet import Fernet

# ✅ یکبار setup logging (در اول فایل، بعد از imports)
logger = logging.getLogger(__name__)

# 🟢 Database instance
db = Database()

# ✅ ThreadPoolExecutor برای کارهای sync
EXECUTOR = ThreadPoolExecutor(max_workers=10)

logger.debug("📦 admin_panel.py module loaded")


# ==============================================================================
# 🛡️ UTILITY FUNCTIONS
# ==============================================================================

async def safe_edit_message(update: Update, text: str, reply_markup=None, parse_mode: str = "Markdown", **kwargs):
    """Safely edit an existing bot message.

    - Works for callback_query edits (most common).
    - If message_id/chat_id are provided, can also edit a specific message via bot.edit_message_text.
    - On parse errors (bad markdown), it retries without parse_mode.
    """
    # Accept and ignore unexpected kwargs (backward compatibility)
    message_id = kwargs.pop("message_id", None)
    chat_id = kwargs.pop("chat_id", None)

    def _sanitize(t: str) -> str:
        # Remove common markdown tokens that often break entity parsing.
        return (
            str(t)
            .replace("`", "")
            .replace("*", "")
            .replace("_", "")
            .replace("[", "")
            .replace("]", "")
        )

    try:
        if update.callback_query:
            return await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )

        # Fallback: edit a specific message if IDs are provided
        if message_id is not None and chat_id is not None:
            return await update.get_bot().edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )

        # Final fallback: send a new message
        if update.message:
            return await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
        return None

    except Exception as e:
        logger.warning("⚠️ safe_edit_message failed: %s", e, exc_info=True)

        # Retry without parse_mode to avoid markdown entity errors
        try:
            clean = _sanitize(text)
            if update.callback_query:
                return await update.callback_query.edit_message_text(
                    text=clean,
                    reply_markup=reply_markup,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
            if message_id is not None and chat_id is not None:
                return await update.get_bot().edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=clean,
                    reply_markup=reply_markup,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
            if update.message:
                return await update.message.reply_text(
                    text=clean,
                    reply_markup=reply_markup,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
        except Exception:
            pass
        return None



# ==============================================================================
# 👑 ADMIN PANEL HANDLERS
# ==============================================================================

async def admin_panel_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی اصلی پنل مدیریت."""
    if update.effective_user.id != SUPER_ADMIN_ID:
        logger.warning(f"❌ Unauthorized admin access attempt by {update.effective_user.id}")
        return
    
    try:
        users_count = len(db.get_all_users())
        logger.debug(f"👥 Total users: {users_count}")
        
        # ✅ اصلاح شد:  باز کردن صحیح کانکشن و نشانگر
        with db.get_connection() as (conn, cur):
            cur.execute('SELECT id FROM servers')
            total_servers = len(cur.fetchall())
            logger.debug(f"🖥 Total servers: {total_servers}")

        reply_markup = keyboard.admin_main_kb()
        txt = (
            f"🤖 **پنل مدیریت ربات**\n\n"
            f"📊 **آمار کلی:**\n"
            f"👤 کل کاربران: `{users_count}`\n"
            f"🖥 کل سرورهای ثبت شده: `{total_servers}`"
        )
        
        await safe_edit_message(update, txt, reply_markup=reply_markup)
        logger.info(f"✅ Admin panel displayed")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_panel_main: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا:  {e}")


# ==============================================================================
# 🛠 AGENT MANAGEMENT DASHBOARD
# ==============================================================================

async def admin_agent_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """داشبورد وضعیت ایجنت‌ها (همه سرورها)."""
    if update.effective_user.id != SUPER_ADMIN_ID: 
        logger.warning(f"❌ Unauthorized agent dashboard access by {update.effective_user.id}")
        return

    try:
        servers = db.get_all_servers()
        if not servers:
            await safe_edit_message(
                update, 
                "📭 هیچ سروری در دیتابیس ثبت نشده است.", 
                reply_markup=keyboard.back_btn('admin_panel_main')
            )
            logger.info("⚠️ No servers found in database")
            return

        logger.info(f"🔍 Checking status of {len(servers)} servers...")
        
        # برای جلوگیری از فشار زیاد، همزمانی را محدود می‌کنیم
        sem = asyncio.Semaphore(10)

        async def _probe(s):
            """تست وضعیت یک سرور."""
            async with sem:
                ip = s. get('ip')
                # پروتکل فعلی:  token=password
                token = sec.decrypt(s['password']) if s.get('password') else ''
                try:
                    logger.debug(f"🔌 Probing {ip}...")
                    res = await ServerMonitor.check_full_stats_ws(ip, int(AGENT_PORT), token)
                except Exception as e:
                    logger.warning(f"⚠️ Probe failed for {ip}: {e}")
                    res = {'status': 'Offline', 'error': str(e)}
                
                # ذخیره در DB برای نمایش لاگ/آخرین وضعیت
                now = get_tehran_datetime().strftime('%Y-%m-%d %H:%M:%S')
                if res. get('status') == 'Online':
                    db.update_agent_state(s['id'], status='Online', last_log='OK', last_seen=now)
                    db.update_server_error(s['id'], '')
                    logger.debug(f"✅ Server {ip} is Online")
                else: 
                    err = str(res.get('error') or 'Unknown')
                    # اگر خطای auth باشد، همان وضعیت را روی last_status هم اعمال می‌کنیم
                    if 'auth' in err.lower():
                        db. update_status(s['id'], 'Auth Failed')
                        logger.warning(f"🔐 Auth failed for {ip}")
                    db.update_agent_state(s['id'], status='', last_log=err, last_seen=now)
                    db.update_server_error(s['id'], err)
                    logger.warning(f"❌ Server {ip} is Offline: {err}")
                
                return s['id'], res

        # اجرای تسک‌های پروب
        results = await asyncio.gather(*[_probe(s) for s in servers], return_exceptions=True)

        # تجزیه نتایج
        online = 0
        offline = 0
        lines = []
        
        for item in results:
            if isinstance(item, Exception):
                logger.error(f"❌ Probe exception:  {item}")
                continue
            
            sid, res = item
            srv = next((x for x in servers if x['id'] == sid), None)
            if not srv:
                continue
            
            if res.get('status') == 'Online':
                online += 1
                lines.append(f"🟢 `{sid}` | {srv['name']} | {srv['ip']}")
            else:
                offline += 1
                err = str(res.get('error') or 'Offline')
                # کوتاه‌سازی متن
                if len(err) > 42:
                    err = err[: 42] + '.. .'
                lines.append(f"🔴 `{sid}` | {srv['name']} | {srv['ip']} | `{err}`")

        txt = (
            "🛠 **تنظیمات و وضعیت ایجنت‌ها**\n\n"
            f"🔌 پورت ایجنت (Config): `{AGENT_PORT}`\n"
            f"🟢 آنلاین: `{online}` | 🔴 آفلاین: `{offline}`\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            + "\n".join(lines[: 35])
            + ("\n..." if len(lines) > 35 else "")
        )

        kb = [
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin_agent_dashboard')],
            [InlineKeyboardButton("📄 مشاهده لاگ اتصال.. .", callback_data='admin_agent_logs')],
            [InlineKeyboardButton("🔌 تلاش مجدد برای اتصال (Reconnect All)", callback_data='admin_agent_reconnect_all')],
            [InlineKeyboardButton("🧩 نصب/رفع ایجنت‌ها", callback_data='admin_agent_install_menu')],
            [InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_main')],
        ]
        
        await safe_edit_message(update, txt, reply_markup=InlineKeyboardMarkup(kb))
        logger.info(f"✅ Agent dashboard displayed:  {online} online, {offline} offline")
        
    except Exception as e: 
        logger.error(f"❌ Error in admin_agent_dashboard: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا: {e}")


async def admin_agent_logs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی انتخاب سرور برای مشاهده لاگ اتصال ایجنت."""
    if update.effective_user.id != SUPER_ADMIN_ID:
        logger.warning(f"❌ Unauthorized agent logs access by {update.effective_user.id}")
        return
    
    try:
        servers = db.get_all_servers()
        if not servers:
            await safe_edit_message(
                update,
                "📭 هیچ سروری ثبت نشده است.",
                reply_markup=keyboard. back_btn('admin_panel_main')
            )
            logger.info("⚠️ No servers found")
            return

        kb = []
        for s in servers[: 50]: 
            status_icon = "🟢" if s.get('last_status') == 'Online' else "🔴"
            kb. append([InlineKeyboardButton(
                f"{status_icon} {s['name']}",
                callback_data=f"admin_agent_log_{s['id']}"
            )])
        
        kb. append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin_agent_dashboard')])
        
        await safe_edit_message(
            update,
            "📄 **انتخاب سرور برای مشاهده آخرین لاگ اتصال ایجنت**",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        logger.info(f"✅ Agent logs menu displayed with {len(servers)} servers")
        
    except Exception as e: 
        logger.error(f"❌ Error in admin_agent_logs_menu: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا: {e}")


async def admin_agent_log_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لاگ اتصال ایجنت برای یک سرور خاص."""
    if update. effective_user.id != SUPER_ADMIN_ID:
        logger.warning(f"❌ Unauthorized agent log view by {update.effective_user.id}")
        return
    
    try:
        sid = int(update.callback_query.data. split('_')[-1])
    except Exception as e:
        logger.error(f"❌ Invalid server ID:  {e}")
        await update. callback_query.answer("❌ شناسه نامعتبر", show_alert=True)
        return

    try:
        srv = db.get_server_by_id(sid)
        if not srv:
            await safe_edit_message(
                update,
                "❌ سرور یافت نشد.",
                reply_markup=keyboard. back_btn('admin_agent_dashboard')
            )
            logger.warning(f"⚠️ Server {sid} not found")
            return

        txt = (
            f"📄 **آخرین لاگ اتصال ایجنت**\n\n"
            f"🆔 `{srv['id']}`\n"
            f"📛 {srv['name']}\n"
            f"🌐 `{srv['ip']}`\n\n"
            f"🕒 آخرین مشاهده: `{srv. get('agent_last_seen') or 'N/A'}`\n"
            f"🧾 لاگ:  `{(srv.get('agent_last_log') or srv. get('last_error') or 'N/A')}`"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data='admin_agent_dashboard')],
            [InlineKeyboardButton("🔙 بازگشت", callback_data='admin_agent_logs')],
        ])
        
        await safe_edit_message(update, txt, reply_markup=kb)
        logger.info(f"✅ Agent log viewed for server {sid}")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_agent_log_view: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا:  {e}")


async def admin_agent_reconnect_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ریست کردن تمام اتصال‌های WebSocket (reconnect)."""
    if update.effective_user.id != SUPER_ADMIN_ID:
        logger. warning(f"❌ Unauthorized reconnect by {update.effective_user.id}")
        return
    
    try:
        logger.info("🔄 Reconnecting all WebSocket connections...")
        await ws_reconnect_all()
    except Exception as e:
        logger.error(f"❌ Reconnect failed: {e}", exc_info=True)
        pass
    
    try:
        await update.callback_query.answer(
            "✅ تمام اتصال‌ها ریست شد؛ تلاش مجدد در اولین درخواست انجام می‌شود.",
            show_alert=True
        )
    except Exception as e:
        logger.warning(f"⚠️ Callback answer failed: {e}")
        pass
    
    await admin_agent_dashboard(update, context)
    logger.info("✅ Reconnect completed")


# ==============================================================================
# 👥 USER MANAGEMENT
# ==============================================================================

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست کاربران با صفحه‌بندی."""
    try:
        page = int(update.callback_query.data.split('_')[-1])
    except Exception as e:
        logger.error(f"❌ Invalid page number: {e}")
        page = 1

    try:
        users, total_count = db.get_all_users_paginated(page, 5)
        total_pages = (total_count + 4) // 5

        txt = f"👥 **لیست کاربران (صفحه {page} از {total_pages})**\nتعداد کل:  `{total_count}`\n➖➖➖➖➖➖"
        reply_markup = keyboard.admin_users_list_kb(users, page, total_pages)
        
        await safe_edit_message(update, txt, reply_markup=reply_markup)
        logger.info(f"✅ Users list displayed (page {page})")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_users_list: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا: {e}")


async def admin_user_manage(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    """مدیریت یک کاربر خاص (نمایش جزئیات و گزینه‌های عمل)."""
    if not user_id and update.callback_query: 
        data = update.callback_query.data
        if "manage_" in data:
            try:
                user_id = int(data.split('_')[-1])
            except Exception as e:
                logger. error(f"❌ Parse manage_ callback failed: {e}")
                pass

    if not user_id: 
        await safe_edit_message(update, "❌ خطای سیستمی:  آیدی کاربر پیدا نشد.")
        logger.error("❌ admin_user_manage: user_id is None")
        return

    try: 
        user = db.get_user(user_id)
        if not user:
            await safe_edit_message(update, "❌ کاربر در دیتابیس یافت نشد.")
            logger.warning(f"⚠️ User {user_id} not found in database")
            return

        plan_txt = "💎 پریمیوم (VIP)" if user['plan_type'] == 1 else "👤 عادی (Normal)"
        ban_status = "🔴 مسدود" if user['is_banned'] else "🟢 فعال"

        txt = (
            f"👤 **مدیریت کاربر:** `{user['full_name']}`\n"
            f"🆔 آیدی: `{user['user_id']}`\n"
            f"💳 **نوع اشتراک:** {plan_txt}\n"
            f"📆 انقضا: `{user['expiry_date']}`\n"
            f"📡 وضعیت: {ban_status}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"📊 سرورها: `{len(db.get_all_user_servers(user_id))}` / `{user['server_limit']}`"
        )
        reply_markup = keyboard.admin_user_manage_kb(user_id, user['plan_type'], user['is_banned'])
        await safe_edit_message(update, txt, reply_markup=reply_markup)
        logger.info(f"✅ User management panel displayed for {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_user_manage:  {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا: {e}")


async def admin_user_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای عمل‌های مختلف روی کاربران (ban, delete, add time, etc)."""
    try:
        data = update.callback_query.data
        action = data.split('_')[2]
        target_id = int(data.split('_')[3])
    except Exception as e:
        logger.error(f"❌ Parse user action failed: {e}")
        await update.callback_query.answer("❌ خطای تجزیه دستور", show_alert=True)
        return

    try:
        if action == 'ban':
            new_state = db.toggle_ban_user(target_id)
            msg = "کاربر مسدود شد." if new_state else "کاربر فعال شد."
            try:
                await update.callback_query.answer(msg)
            except Exception as e:
                logger.warning(f"⚠️ Callback answer failed: {e}")
            await admin_user_manage(update, context, user_id=target_id)
            logger.info(f"✅ User {target_id} ban toggled to {new_state}")

        elif action == 'del':
            db.remove_user(target_id)
            try:
                await update.callback_query.answer("کاربر حذف شد.")
            except Exception as e:
                logger.warning(f"⚠️ Callback answer failed: {e}")
            await admin_users_list(update, context)
            logger.info(f"✅ User {target_id} deleted")

        elif action == 'addtime':
            db.add_or_update_user(target_id, days=30)
            try:
                await update.callback_query. answer("30 روز تمدید شد.")
            except Exception as e:
                logger.warning(f"⚠️ Callback answer failed: {e}")
            await admin_user_manage(update, context, user_id=target_id)
            logger.info(f"✅ User {target_id} extended by 30 days")

        elif action == 'limit':
            context.user_data['target_uid'] = target_id
            await safe_edit_message(update, "🔢 **تعداد جدید محدودیت سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
            return ADMIN_SET_LIMIT

        elif action == 'settime':
            context.user_data['target_uid'] = target_id
            await safe_edit_message(update, "📅 **تعداد روز اعتبار را وارد کنید (مثلا 60):**", reply_markup=keyboard.get_cancel_markup())
            return ADMIN_SET_TIME_MANUAL

        elif action == 'toggleplan':
            new_plan = db.toggle_user_plan(target_id)
            msg = "✅ کاربر به پریمیوم ارتقا یافت" if new_plan == 1 else "⬇️ کاربر به عادی تغییر یافت"
            try:
                await update.callback_query.answer(msg, show_alert=True)
            except Exception as e:
                logger.warning(f"⚠️ Callback answer failed: {e}")
            await admin_user_manage(update, context, user_id=target_id)
            logger.info(f"✅ User {target_id} plan toggled to {new_plan}")
            
    except Exception as e:
        logger.error(f"❌ Error in admin_user_actions:  {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا:  {e}")


async def admin_set_limit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد محدودیت سرور جدید از کاربر."""
    try:
        lim = int(update.message.text)
        target_id = context.user_data. get('target_uid')
        db.update_user_limit(target_id, lim)
        await update.message.reply_text(f"✅ محدودیت سرور به {lim} تغییر یافت.")
        await admin_user_manage(update, context, user_id=target_id)
        logger.info(f"✅ User {target_id} limit set to {lim}")
        return ConversationHandler.END
    except ValueError:
        await update.message. reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید.")
        logger.warning(f"⚠️ Invalid limit input: {update.message.text}")
        return ADMIN_SET_LIMIT
    except Exception as e:
        logger.error(f"❌ Error in admin_set_limit_handler: {e}", exc_info=True)
        await update.message.reply_text(f"❌ خطا:  {e}")
        return ADMIN_SET_LIMIT


async def admin_set_days_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد روز اعتبار جدید از کاربر."""
    try:
        days = int(update.message.text)
        target_id = context. user_data.get('target_uid')
        db.add_or_update_user(target_id, days=days)
        await update.message.reply_text(f"✅ اعتبار کاربر {days} روز تمدید شد.")
        await admin_user_manage(update, context, user_id=target_id)
        logger.info(f"✅ User {target_id} extended by {days} days")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید.")
        logger.warning(f"⚠️ Invalid days input: {update.message. text}")
        return ADMIN_SET_TIME_MANUAL
    except Exception as e:
        logger.error(f"❌ Error in admin_set_days_handler: {e}", exc_info=True)
        await update.message.reply_text(f"❌ خطا: {e}")
        return ADMIN_SET_TIME_MANUAL


async def admin_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع جستجوی کاربر."""
    await safe_edit_message(update, "🔎 **آیدی عددی کاربر را ارسال کنید:**", reply_markup=keyboard.get_cancel_markup())
    logger.info("🔎 Admin user search started")
    return ADMIN_SEARCH_USER


async def admin_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت آیدی کاربر و نمایش جزئیات."""
    try:
        tid = int(update.message.text)
        user = db.get_user(tid)
        if user:
            await admin_user_manage(update, context, user_id=tid)
            logger.info(f"✅ User {tid} found and management panel displayed")
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ کاربر یافت نشد.")
            logger.warning(f"⚠️ User {tid} not found")
            return ADMIN_SEARCH_USER
    except ValueError:
        await update.message.reply_text("❌ فرمت نامعتبر.")
        logger.warning(f"⚠️ Invalid user ID format: {update.message.text}")
        return ADMIN_SEARCH_USER
    except Exception as e:
        logger.error(f"❌ Error in admin_search_handler: {e}", exc_info=True)
        await update.message.reply_text(f"❌ خطا: {e}")
        return ADMIN_SEARCH_USER


async def admin_users_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت لیست تمام کاربران به‌صورت متن."""
    try:
        users = db.get_all_users()
        txt = "📋 **لیست کل کاربران:**\n\n"
        for u in users:
            txt += f"🆔 {u['user_id']} | 👤 {u['full_name']} | 📅 Exp: {u['expiry_date']}\n"

        if len(txt) > 4000:
            with open("users_list.txt", "w", encoding='utf-8') as f:
                f.write(txt)
            try:
                await update.callback_query.message.reply_document(
                    document=open("users_list.txt", "rb"), 
                    caption="لیست کاربران"
                )
            except Exception as e:
                logger.error(f"❌ Document send failed: {e}")
            try:
                os.remove("users_list.txt")
            except:
                pass
        else:
            await update.callback_query.message.reply_text(txt)
        
        logger.info(f"✅ Users text list sent ({len(users)} users)")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_users_text: {e}", exc_info=True)
        await update.callback_query.message.reply_text(f"❌ خطا: {e}")


# ==============================================================================
# 📢 BROADCAST
# ==============================================================================

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ارسال پیام به تمام کاربران."""
    await safe_edit_message(
        update, 
        "📢 **لطفاً پیام خود را ارسال کنید:**\n\nبرای تمام کاربران ارسال می‌شود.", 
        reply_markup=keyboard.get_cancel_markup()
    )
    logger.info("📢 Broadcast started")
    return GET_BROADCAST_MSG


async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام به تمام کاربران."""
    try:
        users = db.get_all_users()
        total = len(users)
        success = 0
        blocked = 0
        
        status_msg = await update.message.reply_text(f"⏳ در حال ارسال به {total} کاربر...")
        logger.info(f"📢 Broadcasting message to {total} users...")

        for user in users:
            try: 
                await update.message.copy(chat_id=user['user_id'])
                success += 1
            except Exception as e:
                blocked += 1
                logger.debug(f"⚠️ Broadcast failed for user {user['user_id']}: {e}")
            
            if success % 20 == 0:
                await asyncio.sleep(1)

        await status_msg.edit_text(
            f"✅ **ارسال شد.**\n👥 کل: `{total}`\n✅ موفق: `{success}`\n🚫 ناموفق: `{blocked}`"
        )
        await admin_panel_main(update, context)
        logger.info(f"✅ Broadcast completed:  {success} successful, {blocked} blocked")
        return ConversationHandler.END
        
    except Exception as e: 
        logger.error(f"❌ Error in admin_broadcast_send: {e}", exc_info=True)
        await update. message.reply_text(f"❌ خطا: {e}")
        return ConversationHandler.END


# ==============================================================================
# ➕ ADD NEW USER
# ==============================================================================

async def add_new_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع افزودن کاربر جدید."""
    try:
        await update.callback_query.answer()
    except: 
        pass
    
    await safe_edit_message(
        update, 
        "👤 **شناسه عددی (User ID) کاربر را وارد کنید:**", 
        reply_markup=keyboard.get_cancel_markup()
    )
    logger.info("👤 Add new user started")
    return ADD_ADMIN_ID


async def get_new_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت آیدی کاربر جدید."""
    try:
        context.user_data['new_uid'] = int(update.message.text)
        await update.message.reply_text("📅 **تعداد روز اعتبار:**", reply_markup=keyboard.get_cancel_markup())
        logger.info(f"👤 New user ID received: {context.user_data['new_uid']}")
        return ADD_ADMIN_DAYS
    except ValueError:
        await update.message.reply_text("❌ فقط عدد وارد کنید.")
        logger.warning(f"⚠️ Invalid new user ID:  {update.message.text}")
        return ADD_ADMIN_ID
    except Exception as e:
        logger.error(f"❌ Error in get_new_user_id: {e}", exc_info=True)
        await update.message.reply_text(f"❌ خطا:  {e}")
        return ADD_ADMIN_ID


async def get_new_user_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد روز اعتبار و افزودن کاربر."""
    try:
        days = int(update.message.text)
        new_uid = context.user_data. get('new_uid')
        db.add_or_update_user(new_uid, full_name="User (Manual)", days=days)
        await update.message.reply_text("✅ کاربر افزوده شد.")
        await admin_panel_main(update, context)
        logger.info(f"✅ New user added:  {new_uid} with {days} days")
        return ConversationHandler.END
    except ValueError:
        await update. message.reply_text("❌ فقط عدد وارد کنید.")
        logger.warning(f"⚠️ Invalid days input: {update. message.text}")
        return ADD_ADMIN_DAYS
    except Exception as e:
        logger.error(f"❌ Error in get_new_user_days: {e}", exc_info=True)
        await update. message.reply_text(f"❌ خطا: {e}")
        return ADD_ADMIN_DAYS


# ==============================================================================
# 📜 GLOBAL SERVER REPORTS
# ==============================================================================

async def admin_all_servers_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش گزارش سرورهای تمام کاربران (با صفحه‌بندی)."""
    if update.effective_user.id != SUPER_ADMIN_ID:
        return
    
    try:
        query = update.callback_query
        try:
            page = int(query.data.split('_')[-1])
        except:
            page = 1
        
        ITEMS_PER_PAGE = 3
        all_users = db.get_all_users()
        users_with_active_servers = []
        
        for u in all_users:
            servers = db.get_all_user_servers(u['user_id'])
            if any(s['is_active'] == 1 for s in servers):
                users_with_active_servers.append(u)

        total = len(users_with_active_servers)
        total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        start_idx = (page - 1) * ITEMS_PER_PAGE
        current_users = users_with_active_servers[start_idx:start_idx + ITEMS_PER_PAGE]

        txt = f"📜 **لیست کاربران دارای سرور فعال**\n📄 صفحه `{page}` از `{total_pages}`\n➖➖➖➖➖➖\n"
        
        for u in current_users:
            servers = db.get_all_user_servers(u['user_id'])
            active = [s for s in servers if s['is_active']]
            txt += f"👤 **{u['full_name']}** (`{u['user_id']}`)\n📦 فعال:  `{len(active)}`\n"
            
            for i, s in enumerate(active, 1):
                status = "🟢" if s['last_status'] == 'Online' else "🔴"
                expiry = s['expiry_date']. split(' ')[0] if s['expiry_date'] else "♾"
                txt += f"   {i}. {status} **{s['name']}** | 📅 {expiry}\n"
            txt += "➖\n"

        reply_markup = keyboard.admin_global_report_kb(page, total_pages)
        await safe_edit_message(update, txt, reply_markup=reply_markup)
        logger.info(f"✅ Global report displayed (page {page})")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_all_servers_report: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا:  {e}")


async def admin_full_report_global_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع تولید گزارش جامع تمام سرورها."""
    try:
        await update.callback_query.answer("⏳ شروع گزارش جامع...")
        await update.callback_query.message.reply_text("⚠️ **شروع آنالیز تمام سرورها.. .**\nلطفاً صبور باشید.")
        logger.info("🔄 Full global report started")
        asyncio.create_task(run_full_global_report(context, update. effective_chat.id))
    except Exception as e:
        logger.error(f"❌ Error in admin_full_report_global_action: {e}", exc_info=True)


async def run_full_global_report(context, chat_id):
    """اجرای تولید گزارش جامع سرورها."""
    try:
        loop = asyncio.get_running_loop()
        
        # استفاده از executor برای دریافت لیست (sync)
        all_servers = await loop.run_in_executor(EXECUTOR, db.get_all_servers)
        active_servers = [s for s in all_servers if s['is_active']]

        if not active_servers:
            await context.bot.send_message(chat_id, "❌ سرور فعالی یافت نشد.")
            logger.warning("⚠️ No active servers found for report")
            return
        
        logger.info(f"📊 Generating report for {len(active_servers)} active servers...")
        
        sem = asyncio.Semaphore(10)
        
        async def safe_check(s):
            """بررسی ایمن‌تر وضعیت سرور."""
            async with sem:
                try: 
                    # ✅ StatsManager.check_full_stats خود async است
                    res = await StatsManager.check_full_stats(
                        s['ip'],
                        s['port'],
                        s['username'],
                        sec. decrypt(s['password'])
                    )
                    return res
                except Exception as e: 
                    logger.error(f"❌ Stats check error for {s['ip']}: {e}")
                    return {'status': 'Offline', 'error': str(e)}

        results = await asyncio.gather(*[safe_check(s) for s in active_servers])
        report_lines = []
        
        for srv, res in zip(active_servers, results):
            if isinstance(res, dict) and res.get('status') == 'Online':
                cpu = ScoreEngine.make_bar(res. get('cpu', 0), 5)
                uptime = res.get('uptime_str', 'N/A')
                report_lines.append(
                    f"🟢 **{srv['name']}**\n"
                    f"   🆔 User: `{srv['owner_id']}`\n"
                    f"   🧠 {cpu} {res.get('cpu', 0)}%\n"
                    f"   ⏱ {uptime}\n"
                )
            else:
                err = res.get('error', 'Unknown Error') if isinstance(res, dict) else str(res)
                report_lines. append(
                    f"🔴 **{srv['name']}**\n"
                    f"   🆔 User: `{srv['owner_id']}`\n"
                    f"   ❌ {err}\n"
                )

        final_report = (
            f"🌍 **گزارش جامع سرورها**\n"
            f"📅 `{get_jalali_str()}`\n"
            f"➖➖➖➖➖➖\n"
            + "\n".join(report_lines)
        )
        
        if len(final_report) > 4000:
            for i in range(0, len(final_report), 4000):
                await context.bot.send_message(
                    chat_id,
                    final_report[i:i+4000],
                    parse_mode='Markdown'
                )
        else:
            await context.bot. send_message(chat_id, final_report, parse_mode='Markdown')
        
        logger.info(f"✅ Full report sent ({len(report_lines)} servers)")
            
    except Exception as e: 
        logger.error(f"❌ run_full_global_report error:  {e}", exc_info=True)
        try:
            await context.bot. send_message(
                chat_id,
                f"❌ خطا در تولید گزارش:  {e}"
            )
        except:
            pass


# ==============================================================================
# 🔎 USER SEARCH & DETAIL
# ==============================================================================

async def admin_search_servers_by_uid_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع جستجوی سرورهای یک کاربر خاص."""
    await safe_edit_message(
        update, 
        "🔎 **آیدی عددی کاربر را ارسال کنید:**", 
        reply_markup=keyboard. get_cancel_markup()
    )
    logger.info("🔎 Search servers by UID started")
    return ADMIN_GET_UID_FOR_REPORT


async def admin_report_by_uid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت آیدی کاربر و نمایش سرورهای آن."""
    try:
        target_uid = int(update.message.text)
        servers = db.get_all_user_servers(target_uid)
        
        if not servers:
            await update.message.reply_text("⚠️ این کاربر سروری ندارد.")
            logger.warning(f"⚠️ User {target_uid} has no servers")
            return ConversationHandler.END
        
        txt = f"🖥 **سرورهای کاربر:** `{target_uid}`\n➖➖➖➖➖➖\n"
        kb = []
        
        for s in servers:
            icon = "🟢" if s['is_active'] else "🔴"
            kb.append([InlineKeyboardButton(f"{icon} {s['name']}", callback_data=f"admin_detail_{s['id']}")])
        
        kb. append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_main')])
        
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))
        logger.info(f"✅ Servers for user {target_uid} displayed")
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ آیدی نامعتبر.")
        logger.warning(f"⚠️ Invalid user ID format: {update.message.text}")
        return ADMIN_GET_UID_FOR_REPORT
    except Exception as e:
        logger.error(f"❌ Error in admin_report_by_uid_handler: {e}", exc_info=True)
        await update.message.reply_text(f"❌ خطا: {e}")
        return ADMIN_GET_UID_FOR_REPORT


async def admin_server_detail_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    callback handler برای جزئیات سرور.
    این تابع صرفاً برای هماهنگی کالبک‌هاست.
    لاجیک اصلی در bot_logic.py (server_detail) است.
    """
    logger.debug("📌 admin_server_detail_action called - delegating to server_detail")
    pass


async def admin_user_servers_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش گزارش سرورهای یک کاربر خاص."""
    try:
        query = update.callback_query
        target_uid = int(query.data.split('_')[3])
        servers = db.get_all_user_servers(target_uid)
        
        if not servers: 
            await query.answer("❌ سروری ندارد.", show_alert=True)
            logger.warning(f"⚠️ User {target_uid} has no servers")
            return

        txt = f"👤 **گزارش سرورهای کاربر {target_uid}**\n\n"
        for s in servers:
            txt += f"🔹 **{s['name']}**\n   🌐 {s['ip']}\n   📡 {s['last_status']}\n\n"
        
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_u_manage_{target_uid}")]]
        await safe_edit_message(update, txt, reply_markup=InlineKeyboardMarkup(kb))
        logger.info(f"✅ User {target_uid} servers report displayed")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_user_servers_report:  {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا:  {e}")
# ==============================================================================
# Agent installer (Admin)
# ==============================================================================

async def admin_agent_install_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی نصب/رفع ایجنت‌ها برای ادمین."""
    try:
        query = update.callback_query
        if query:
            await query.answer()

        servers = db.get_all_servers()
        if not servers:
            await safe_edit_message(update, "❌ هیچ سروری ثبت نشده است.")
            return

        txt = "🧩 **نصب/رفع ایجنت مانیتورینگ (WebSocket Agent)**\n\n" \
              "این بخش با **SSH** به سرور وصل می‌شود، پیش‌نیازها را نصب می‌کند، سرویس `sonar-agent` را می‌سازد/آپدیت می‌کند، سپس اتصال WebSocket را تست می‌کند."

        kb = []
        for s in servers:
            sid = s.get('id')
            name = s.get('name') or f"Server {sid}"
            ip = s.get('ip') or "?"
            kb.append([InlineKeyboardButton(f"🔧 {name} | {ip}", callback_data=f"admin_agent_install_{sid}")])

        kb.append([InlineKeyboardButton("🛠 نصب/تعمیر همه سرورها (انتخاب پورت)", callback_data="admin_agent_install_all")])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data='admin_agent_dashboard')])
        await safe_edit_message(update, txt, reply_markup=InlineKeyboardMarkup(kb))
        logger.info(f"✅ admin_agent_install_menu shown for {len(servers)} servers")

    except Exception as e:
        logger.error(f"❌ Error in admin_agent_install_menu: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا: {e}")


async def admin_agent_install_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای نصب/رفع ایجنت برای یک سرور."""
    query = update.callback_query
    try:
        await query.answer()
        parts = (query.data or '').split('_')
        # Bulk install/repair on ALL servers (asks for a single WS port and applies it everywhere)
        if parts and parts[-1] == "all":
            servers = db.get_all_servers()
            targets = [s.get("id") for s in servers if s.get("id") is not None]
            context.user_data["agent_install_targets"] = targets
            await safe_edit_message(
                update,
                "🔧 لطفاً پورت WebSocket ایجنت را ارسال کنید (مثلاً 8181).\n\nاین پورت روی *همه سرورها* تنظیم و سپس ایجنت نصب/تعمیر می‌شود.",
            )
            return ADMIN_AGENT_PORT_INPUT

        sid = int(parts[-1])

        srv = db.get_server_by_id(sid)
        if not srv:
            await safe_edit_message(update, "❌ سرور پیدا نشد.")
            return

        ip = srv.get('ip')
        ssh_port = int(srv.get('port') or 22)
        username = srv.get('username') or 'root'
        password = sec.decrypt(srv['password']) if srv.get('password') else ''

        msg = await safe_edit_message(
            update,
            f"⏳ در حال آماده‌سازی نصب ایجنت...\n\n🌐 **IP:** `{ip}`\n🔌 **SSH Port:** `{ssh_port}`\n📡 **Agent Port:** `{AGENT_PORT}`",
        )

        loop = asyncio.get_running_loop()

        # مرحله 1: نصب/آپدیت ایجنت (SSH)
        await safe_edit_message(
            update,
            f"⏳ **مرحله 1/2:** نصب/رفع ایجنت و پیش‌نیازها...\n\nاین عملیات با SSH انجام می‌شود و ممکن است چند دقیقه طول بکشد.",
            message_id=msg.message_id,
        )

        ok, out = await loop.run_in_executor(
            EXECUTOR,
            ServerMonitor.install_agent_service,
            ip,
            ssh_port,
            username,
            password,
            AGENT_PORT,
        )

        if not ok:
            await safe_edit_message(
                update,
                "❌ **نصب/رفع ایجنت شکست خورد!**\n\n" + (out or "(بدون خروجی)"),
                message_id=msg.message_id,
            )
            logger.warning(f"❌ Agent install failed for server {sid}: {out}")
            return

        # مرحله 2: تست اتصال WebSocket
        await safe_edit_message(
            update,
            "⏳ **مرحله 2/2:** تست اتصال WebSocket...",
            message_id=msg.message_id,
        )

        ws_ok = False
        stats_or_err = None
        try:
            # 🔧 رفع باگ نسخه ۴.۰: اینجا از متغیر تعریف‌نشده «ws_port» استفاده می‌شد
            # (فقط توی مسیر نصب دسته‌جمعی «همه سرورها» تعریف می‌شد، نه اینجا)
            # نتیجه‌اش NameError بود و تست اتصال تک‌سروری همیشه شکست می‌خورد.
            stats_or_err = await ServerMonitor.check_full_stats_ws(ip, AGENT_PORT, password)
            ws_ok = True
        except Exception as e1:
            # اگر در برخی محیط‌ها sync باشد یا حلقه مشکل داشته باشد، در Thread تست می‌کنیم
            try:
                stats_or_err = await loop.run_in_executor(
                    EXECUTOR,
                    lambda: asyncio.run(ServerMonitor.check_full_stats_ws(ip, AGENT_PORT, password)),
                )
                ws_ok = True
            except Exception as e2:
                ws_ok = False
                stats_or_err = str(e2) if str(e2) else str(e1)

        if not ws_ok:
            await safe_edit_message(
                update,
                "⚠️ **ایجنت نصب شد اما تست WebSocket ناموفق بود.**\n\n" + str(stats_or_err),
                message_id=msg.message_id,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔁 تلاش مجدد", callback_data=f"admin_agent_install_{sid}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data='admin_agent_dashboard')],
                ]),
            )
            logger.warning(f"⚠️ Agent installed but WS test failed for server {sid}: {stats_or_err}")
            return

        await safe_edit_message(
            update,
            "✅ **ایجنت با موفقیت نصب/آپدیت شد و اتصال WebSocket برقرار است.**\n\n" +
            f"🌐 `{ip}:{AGENT_PORT}`\n" +
            "می‌توانید از داشبورد ایجنت وضعیت آنلاین/آفلاین را بررسی کنید.",
            message_id=msg.message_id,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📡 داشبورد ایجنت", callback_data='admin_agent_dashboard')],
                [InlineKeyboardButton("📜 مشاهده لاگ اتصال/پروتکل", callback_data='admin_agent_logs')],
            ]),
        )

        logger.info(f"✅ Agent install+test succeeded for server {sid}")

    except Exception as e:
        logger.error(f"❌ Error in admin_agent_install_run: {e}", exc_info=True)
        await safe_edit_message(update, f"❌ خطا: {e}")


async def admin_agent_port_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives WS port from admin and runs bulk install/repair for stored targets."""
    try:
        if not is_admin(update.effective_user.id):
            return ConversationHandler.END

        text = (update.message.text or "").strip()
        if not text.isdigit():
            await update.message.reply_text("❌ لطفاً فقط عدد پورت را ارسال کنید (مثلاً 8181).", reply_markup=make_cancel_keyboard())
            return ADMIN_AGENT_PORT_INPUT

        ws_port = int(text)
        if ws_port < 1 or ws_port > 65535:
            await update.message.reply_text("❌ پورت نامعتبر است. عددی بین 1 تا 65535 ارسال کنید.", reply_markup=make_cancel_keyboard())
            return ADMIN_AGENT_PORT_INPUT

        targets = context.user_data.get("agent_install_targets") or []
        if not targets:
            await update.message.reply_text("⚠️ لیست سرورها برای نصب/تعمیر پیدا نشد.")
            return ADMIN_PANEL

        msg = await update.message.reply_text(
            f"🛠 شروع نصب/تعمیر ایجنت روی {len(targets)} سرور...\nپورت انتخابی: {ws_port}"
        )

        ok_count = 0
        fail_count = 0
        failures = []

        loop = asyncio.get_running_loop()

        for n, sid in enumerate(targets, start=1):
            srv = db.get_server_by_id(int(sid))
            if not srv:
                fail_count += 1
                failures.append((sid, "SERVER_NOT_FOUND"))
                continue

            ip = srv.get("ip")
            ssh_port = int(srv.get("port") or 22)
            user = srv.get("user") or "root"
            password = sec.decrypt(srv.get("password", ""))  # encrypted in DB

            await safe_edit_message(
                update,
                f"⏳ [{n}/{len(targets)}] در حال نصب/تعمیر روی: {srv.get('name', ip)} ({ip})\n"
                f"SSH: {ssh_port} | WS: {ws_port}",
                message_id=msg.message_id,
                chat_id=msg.chat_id,
            )

            # Persist chosen port per-server (so future probes/monitoring use the same port)
            db.update_server_ws_port(int(sid), int(ws_port))

            def _do_install():
                return ServerMonitor.install_agent_service(ip, ssh_port, user, password, int(ws_port))

            ok, out = await loop.run_in_executor(None, _do_install)
            if ok:
                ok_count += 1
            else:
                fail_count += 1
                failures.append((srv.get('name', sid), out))

        summary = f"✅ انجام شد. موفق: {ok_count} | ناموفق: {fail_count}"
        if failures:
            tail = "\n".join([f"- {name}: {err}" for name, err in failures[:12]])
            summary += "\n\n❌ خطاها (نمونه):\n" + tail

        await safe_edit_message(update, summary, message_id=msg.message_id, chat_id=msg.chat_id)

        # cleanup
        context.user_data.pop("agent_install_targets", None)
        return ADMIN_PANEL

    except Exception as e:
        logger.error("admin_agent_port_input failed: %s", e, exc_info=True)
        await update.message.reply_text(f"❌ خطا: {e}")
        return ADMIN_PANEL
