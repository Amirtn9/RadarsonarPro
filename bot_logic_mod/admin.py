"""
Auto-split module from original bot_logic.py
Section: admin
"""

from bot_logic_mod.base import *  # noqa

# 👑 ADMIN PANEL HANDLERS
# ==============================================================================
import tempfile
from pathlib import Path

async def _admin_denied(update):
    if update.effective_user.id == SUPER_ADMIN_ID and SUPER_ADMIN_ID:
        return False
    msg = update.effective_message
    if msg:
        await msg.reply_text('⛔ این عملیات فقط برای مدیر اصلی مجاز است.')
    return True


def _pg_env():
    env = os.environ.copy()
    env['PGPASSWORD'] = str(DB_CONFIG.get('password', ''))
    return env


def _pg_base():
    return ['-h', str(DB_CONFIG.get('host', 'localhost')),
            '-p', str(DB_CONFIG.get('port', '5432')),
            '-U', str(DB_CONFIG.get('user', 'postgres'))]


async def _pg_process(args, timeout=600):
    proc = await asyncio.create_subprocess_exec(*args, env=_pg_env(),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return False, 'Timeout'
    return proc.returncode == 0, stderr.decode(errors='replace')[-900:]


async def admin_backup_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _admin_denied(update): return
    with tempfile.TemporaryDirectory(prefix='sonar-backup-') as temp:
        path = str(Path(temp) / 'sonar_backup.dump')
        ok, err = await _pg_process(['pg_dump', *_pg_base(), '-Fc', '-f', path,
                                     str(DB_CONFIG['dbname'])])
        if ok:
            with open(path, 'rb') as stream:
                await update.effective_message.reply_document(stream,
                    filename='sonar_backup.dump', caption='📦 PostgreSQL custom backup')
        else:
            await update.effective_message.reply_text('❌ بکاپ ناموفق بود: ' + err)


async def admin_backup_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _admin_denied(update): return ConversationHandler.END
    await safe_edit_message(update,
        '⚠️ بازیابی اطلاعات، جداول فعلی را بازنویسی می‌کند. فایل `.dump` یا `.sql` ارسال کنید.',
        reply_markup=keyboard.get_cancel_markup())
    return ADMIN_RESTORE_DB


async def admin_backup_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _admin_denied(update): return ConversationHandler.END
    doc = update.message.document if update.message else None
    if not doc or not doc.file_name or not doc.file_name.lower().endswith(('.dump', '.sql')):
        await update.message.reply_text('❌ فقط فایل `.dump` یا `.sql` پذیرفته می‌شود.')
        return ADMIN_RESTORE_DB
    if doc.file_size and doc.file_size > 100 * 1024 * 1024:
        await update.message.reply_text('❌ فایل بزرگ‌تر از ۱۰۰ مگابایت است.')
        return ADMIN_RESTORE_DB
    is_dump = doc.file_name.lower().endswith('.dump')
    with tempfile.TemporaryDirectory(prefix='sonar-restore-') as temp:
        path = str(Path(temp) / ('restore.dump' if is_dump else 'restore.sql'))
        tgfile = await doc.get_file()
        await tgfile.download_to_drive(path)
        if is_dump:
            args = ['pg_restore', *_pg_base(), '-d', str(DB_CONFIG['dbname']),
                    '--clean', '--if-exists', '--no-owner', '--no-privileges', '--single-transaction', path]
        else:
            args = ['psql', *_pg_base(), '-v', 'ON_ERROR_STOP=1',
                    '-d', str(DB_CONFIG['dbname']), '--single-transaction', '-f', path]
        ok, error = await _pg_process(args, timeout=1200)
        await update.message.reply_text('✅ بازیابی دیتابیس تمام شد.' if ok
            else '❌ خطا در بازیابی: ' + error)
    return ConversationHandler.END


async def admin_key_backup_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _admin_denied(update): return
    if not os.path.isfile(KEY_FILE):
        await update.effective_message.reply_text('❌ کلید موجود نیست.')
        return
    with open(KEY_FILE, 'rb') as stream:
        await update.effective_message.reply_document(stream, filename='secret.key',
            caption='🔑 کلید محرمانه؛ در جایی امن نگهداری شود.')


async def admin_key_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _admin_denied(update): return ConversationHandler.END
    await safe_edit_message(update, '🗝 فایل secret.key معتبر را ارسال کنید.',
                            reply_markup=keyboard.get_cancel_markup())
    return ADMIN_RESTORE_KEY


async def admin_key_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _admin_denied(update): return ConversationHandler.END
    import core
    f = await update.message.document.get_file()
    with tempfile.TemporaryDirectory(prefix='sonar-key-') as temp:
        tmp = Path(temp) / 'key'
        await f.download_to_drive(str(tmp))
        key = tmp.read_bytes().strip()
        try:
            cipher = Fernet(key)
        except Exception:
            await update.message.reply_text('❌ فایل کلید نامعتبر است؛ کلید فعلی تغییر نکرد.')
            return ConversationHandler.END
        dest = Path(KEY_FILE)
        swap = dest.with_suffix('.key.new')
        swap.write_bytes(key + b'\n')
        swap.chmod(0o600)
        swap.replace(dest)
        core.sec.key = key
        core.sec.cipher = cipher
    await update.message.reply_text('✅ کلید معتبر جایگزین شد. سرویس را ری‌استارت کنید.')
    return ConversationHandler.END

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
