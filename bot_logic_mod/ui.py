"""
Auto-split module from original bot_logic.py
Section: ui
"""

from bot_logic_mod.base import *  # noqa

# 🎮 UI HELPERS & GENERAL HANDLERS
# ==============================================================================
async def safe_edit_message(update: Update, text, reply_markup=None, parse_mode='Markdown'):
    """Safely edit a callback message or reply to a message.

    Returns:
        telegram.Message | None
    """
    try:
        if update.callback_query:
            # اگر متن/کیبورد تغییر نکرده باشد، تلگرام BadRequest می‌دهد.
            return await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        if update.message:
            return await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
    except BadRequest as e:
        # اگر ارور این بود که "Message is not modified"، نادیده بگیر
        if "Message is not modified" in str(e):
            return None
        logger.error(f"Edit Error: {e}")
    except Exception as e:
        logger.error(f"General Edit Error: {e}")
    return None


async def cancel_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    await safe_edit_message(update, "🚫 **عملیات لغو شد.**")
    await asyncio.sleep(1)
    await start(update, context)
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال لاگ خطا به ادمین در تلگرام"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # ساخت متن کامل خطا
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    # پیام خطا برای ارسال به ادمین
    message = (
        f"🚨 **CRITICAL ERROR** 🚨\n\n"
        f"Update: <pre>{html.escape(str(update))}</pre>\n\n"
        f"❌ Error:\n<pre>{html.escape(tb_string[-3500:])}</pre>"
    )
    
    # چاپ در کنسول برای اطمینان
    print(tb_string)

    # ارسال به تلگرام ادمین
    try:
        if SUPER_ADMIN_ID:
            await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=message, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Failed to send error log to admin: {e}")
async def run_background_ssh_task(context: ContextTypes.DEFAULT_TYPE, chat_id, func, *args):
    # بررسی می‌کنیم آیا ظرفیت خالی داریم یا نه
    if GLOBAL_SEMAPHORE.locked():
        try:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ **سرور شلوغ است!**\nلطفاً چند لحظه صبر کنید تا پردازش‌های فعلی تمام شوند.")
        except: pass
        return

    loop = asyncio.get_running_loop()
    
    # ورود به صف پردازش با استفاده از سمافور
    async with GLOBAL_SEMAPHORE:
        try:
            # نکته مهم: اینجا به جای None، متغیر EXECUTOR رو پاس میدیم
            ok, output = await loop.run_in_executor(EXECUTOR, func, *args)
            
            clean_out = html.escape(str(output))
            if len(clean_out) > 3500:
                clean_out = clean_out[:3500] + "\n... (Output Truncated)"

            status_icon = "✅ عملیات با موفقیت انجام شد." if ok else "❌ عملیات با خطا مواجه شد."
            msg_text = (
                f"{status_icon}\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"<pre>{clean_out}</pre>"
            )
            await context.bot.send_message(chat_id=chat_id, text=msg_text, parse_mode='HTML')

        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ خطای غیرمنتظره در عملیات پس‌زمینه:\n{e}")
# ==============================================================================
