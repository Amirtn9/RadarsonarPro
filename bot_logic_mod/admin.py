"""
Auto-split module from original bot_logic.py
Section: admin
"""

from bot_logic_mod.base import *  # noqa

# 👑 ADMIN PANEL HANDLERS
# ==============================================================================
async def admin_backup_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت بکاپ دستی Postgres"""
    try: await update.callback_query.answer("⏳ در حال تهیه بکاپ...")
    except: pass

    timestamp = get_tehran_datetime().strftime("%Y-%m-%d_%H-%M")
    backup_file = f"manual_backup_{timestamp}.sql"

    try:
        env = os.environ.copy()
        env['PGPASSWORD'] = DB_CONFIG['password']

        cmd = [
            "pg_dump", "-h", DB_CONFIG['host'], "-U", DB_CONFIG['user'],
            "-d", DB_CONFIG['dbname'], "-f", backup_file
        ]
        
        proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        await proc.wait()

        if proc.returncode == 0:
            await update.callback_query.message.reply_document(
                document=open(backup_file, 'rb'),
                caption=f"📦 Manual Backup: {get_jalali_str()}"
            )
        else:
            await update.callback_query.message.reply_text("❌ خطا در تهیه بکاپ.")
            
    except Exception as e:
        await update.callback_query.message.reply_text(f"❌ خطا: {e}")
    finally:
        if os.path.exists(backup_file): os.remove(backup_file)
async def admin_backup_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(
        update,
        "⚠️ **هشدار:** با آپلود فایل جدید، دیتابیس فعلی بازنویسی می‌شود.\n\n📂 **فایل بکاپ `.sql` را ارسال کنید:**",
        reply_markup=keyboard.get_cancel_markup()
    )
    return ADMIN_RESTORE_DB

async def admin_backup_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگردانی دیتابیس Postgres از فایل SQL"""
    doc = update.message.document
    # چک کردن پسوند فایل (باید sql باشد نه db)
    if not (doc.file_name.endswith('.sql') or doc.file_name.endswith('.txt')):
        await update.message.reply_text("❌ فرمت فایل نامعتبر است. لطفاً فایل `.sql` ارسال کنید.")
        return ADMIN_RESTORE_DB

    temp_name = "temp_restore.sql"
    f = await doc.get_file()
    await f.download_to_drive(temp_name)

    msg = await update.message.reply_text("⏳ **در حال بازنشانی دیتابیس...**\n(این عملیات ممکن است کمی طول بکشد)")

    try:
        env = os.environ.copy()
        env['PGPASSWORD'] = DB_CONFIG['password']

        # دستور بازگردانی (psql)
        # نکته: دیتابیس قبلی پاک نمی‌شود، بلکه روی آن نوشته می‌شود. 
        # اگر می‌خواهید کامل جایگزین شود، باید ابتدا جداول را DROP کنید که کمی پیچیده است.
        # این دستور استاندارد ریستور است:
        cmd = [
            "psql", "-h", DB_CONFIG['host'], "-U", DB_CONFIG['user'],
            "-d", DB_CONFIG['dbname'], "-f", temp_name
        ]

        proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        await proc.wait()

        if proc.returncode == 0:
            await msg.edit_text("✅ **دیتابیس با موفقیت بازنشانی شد.**\nربات اکنون با داده‌های جدید کار می‌کند.")
            await start(update, context)
        else:
            await msg.edit_text("❌ خطا در اجرای دستور psql.")

    except Exception as e:
        await msg.edit_text(f"❌ خطا در بازنشانی: {e}")
    finally:
        if os.path.exists(temp_name): os.remove(temp_name)
    
    return ConversationHandler.END
async def admin_key_backup_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(KEY_FILE):
        try: await update.callback_query.answer("❌ فایل کلید یافت نشد!", show_alert=True)
        except: pass
        return
    await update.callback_query.message.reply_document(document=open(KEY_FILE, 'rb'), caption="🔑 **فایل کلید امنیتی (Secret Key)**\n⚠️ این فایل را برای روز مبادا نگه دارید.")

async def admin_key_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "🗝 **لطفاً فایل secret.key را ارسال کنید:**", reply_markup=keyboard.get_cancel_markup())
    return ADMIN_RESTORE_KEY

async def admin_key_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = await update.message.document.get_file()
    await f.download_to_drive("temp_key.key")
    if os.path.exists(KEY_FILE): os.remove(KEY_FILE)
    os.rename("temp_key.key", KEY_FILE)
    global sec
    sec = Security()
    await update.message.reply_text("✅ **کلید امنیتی بازیابی شد!**")
    await start(update, context)
    return ConversationHandler.END

# ==============================================================================
# 💳 PAYMENT SETTINGS (ADMIN)
# ==============================================================================
async def admin_payment_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    methods = db.get_payment_methods()
    txt = "💳 **مدیریت روش‌های پرداخت**\n\nلیست روش‌های فعال:\n" + ("❌ هیچ روش پرداختی تعریف نشده است." if not methods else "")
    reply_markup = keyboard.admin_pay_settings_kb(methods)
    if update.callback_query:
        await safe_edit_message(update, txt + "\n\n👇 برای حذف روی دکمه‌ها بزنید.", reply_markup=reply_markup)

async def delete_payment_method_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p_id = int(update.callback_query.data.split('_')[3])
    db.delete_payment_method(p_id)
    await update.callback_query.answer("🗑 حذف شد.")
    await admin_payment_settings(update, context)

async def add_pay_method_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p_type = update.callback_query.data.split('_')[3]
    context.user_data['new_pay_type'] = p_type
    msg = "🏦 **نام بانک را وارد کنید:**\n(مثال: بانک ملت)" if p_type == 'card' else "💎 **نام ارز و شبکه را وارد کنید:**\n(مثال: USDT - TRC20 یا TON)"
    await safe_edit_message(update, msg, reply_markup=keyboard.get_cancel_markup())
    return ADD_PAY_NET

async def get_pay_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_pay_net'] = update.message.text
    p_type = context.user_data['new_pay_type']
    msg = "🔢 **شماره کارت را وارد کنید:**" if p_type == 'card' else "🔗 **آدرس ولت (Wallet Address) را ارسال کنید:**"
    await update.message.reply_text(msg, reply_markup=keyboard.get_cancel_markup())
    return ADD_PAY_ADDR

async def get_pay_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_pay_addr'] = update.message.text
    msg = "👤 **نام صاحب حساب را وارد کنید:**" if context.user_data['new_pay_type'] == 'card' else "📝 **توضیحات کوتاه یا نام ولت:**\n(مثال: ولت اصلی)"
    await update.message.reply_text(msg, reply_markup=keyboard.get_cancel_markup())
    return ADD_PAY_HOLDER

async def get_pay_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    holder = update.message.text
    data = context.user_data
    db.add_payment_method(data['new_pay_type'], data['new_pay_net'], data['new_pay_addr'], holder)
    await update.message.reply_text("✅ **روش پرداخت با موفقیت اضافه شد.**")
    kb = [[InlineKeyboardButton("بازگشت به مدیریت پرداخت", callback_data='admin_pay_settings')]]
    await update.message.reply_text("جهت مشاهده لیست، دکمه زیر را بزنید:", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

# ==============================================================================
