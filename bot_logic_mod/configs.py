"""
Auto-split module from original bot_logic.py
Section: configs
"""

from bot_logic_mod.base import *  # noqa

# 📝 CONFIG MANAGEMENT (NEW GRAPHICAL MENU)
# ==============================================================================

async def add_config_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع پروسه افزودن کانفیگ - دریافت لینک"""
    if update.callback_query:
        await update.callback_query.answer()
        
    txt = (
        "📥 **افزودن کانفیگ جدید**\n\n"
        "لطفاً لینک خود را ارسال کنید (پشتیبانی از تمام پروتکل‌ها).\n"
        "ما خودمان نوع آن را تشخیص می‌دهیم یا از شما می‌پرسیم.\n\n"
        "👇 لینک (vmess/vless/http...) را ارسال کنید:"
    )
    
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_CONFIG_LINKS


# --- هندلرهای انتخاب حالت (Mode) ---

async def mode_ask_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    txt = (
        "📄 **لطفاً کانفیگ JSON خود را ارسال کنید.**\n\n"
        "می‌توانید:\n"
        "1️⃣ متن JSON را همینجا پیست کنید.\n"
        "2️⃣ فایل `.json` را آپلود کنید.\n\n"
        "⚠️ ساختار باید استاندارد Xray Outbound باشد."
    )
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_JSON_CONF


async def mode_ask_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    txt = (
        "🔗 **لطفاً لینک سابسکریپشن را ارسال کنید.**\n\n"
        "فرمت مثال:\n"
        "`https://example.com/sub/xyz...`"
    )
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return GET_SUB_LINK


# --- پردازش فایل یا متن JSON ---

async def process_json_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    config_content = ""

    # ۱. دریافت محتوا (متن یا فایل)
    if update.message.document:
        f = await update.message.document.get_file()
        byte_arr = await f.download_as_bytearray()
        config_content = byte_arr.decode('utf-8')
    elif update.message.text:
        config_content = update.message.text
    else:
        await update.message.reply_text("❌ لطفاً فقط متن یا فایل ارسال کنید.")
        return GET_JSON_CONF

    # ۲. اعتبارسنجی JSON
    try:
        data = json.loads(config_content)
        # اگر جیسون معتبر بود، اسمش را از تگ برمی‌داریم
        name = data.get('tag', f"JSON_{int(time.time())}")

        # ذخیره در دیتابیس (کانفیگ را فشرده می‌کنیم)
        minified_json = json.dumps(data)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with db.get_connection() as (conn, cur):
            # استفاده از %s برای پستگرس
            cur.execute(
                "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at) VALUES (%s, 'json', %s, %s, %s)",
                (uid, minified_json, name, now)
            )
            conn.commit()

        await update.message.reply_text(f"✅ **کانفیگ JSON با موفقیت ثبت شد.**\n🏷 نام: `{name}`")
        await asyncio.sleep(1)
        await start(update, context)
        return ConversationHandler.END

    except json.JSONDecodeError:
        await update.message.reply_text("❌ **فرمت JSON نامعتبر است!**\nلطفاً کدهای ارسالی را چک کنید.")
        return GET_JSON_CONF
    except Exception as e:
        await update.message.reply_text(f"❌ خطای ناشناخته: {e}")
        return ConversationHandler.END

async def process_sub_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    uid = update.effective_user.id

    if not link.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ لینک باید با http یا https شروع شود.")
        return GET_SUB_LINK

    msg = await update.message.reply_text("⏳ **در حال دریافت و آنالیز کانفیگ‌ها...**")

    # دریافت اطلاعات سرور ایران
    with db.get_connection() as (conn, cur):
        # FIX: psycopg2 cursor.execute() returns None; use cursor.fetchone()
        cur.execute("SELECT * FROM servers WHERE is_monitor_node=1")
        monitor = cur.fetchone()

    if not monitor:
        await msg.edit_text("❌ سرور مانیتورینگ فعال نیست.")
        return ConversationHandler.END

    ip, port, user = monitor['ip'], monitor['port'], monitor['username']
    password = sec.decrypt(monitor['password'])
    cmd = f"python3 /root/monitor_agent.py {shlex.quote(link)}"

    loop = asyncio.get_running_loop()
    # افزایش تایم‌اوت به 30 ثانیه برای ساب‌های سنگین
    ok, output = await ServerMonitor.run_remote_command(ip, port, user, password, cmd, 30)

    try:
        data = None
        for line in output.split('\n'):
            line = line.strip()
            if not line: continue
            try:
                temp = json.loads(line)
                if temp.get('type') == 'sub':
                    data = temp
                    break
            except:
                pass
        if not data:
            data = extract_safe_json(output)

        if not data:
             raise Exception("Invalid Agent Output (No JSON found)")
        
        if data.get('type') == 'sub':
            configs = data.get('configs', [])
            count = len(configs)

            if count == 0:
                await msg.edit_text("❌ کانفیگی یافت نشد.")
                return ConversationHandler.END
            
            # نام‌گذاری ساب
            sub_name = f"Sub_{int(time.time())}"
            if "remarks" in link:
                 try: sub_name = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get('remarks', [sub_name])[0]
                 except: pass

            await msg.edit_text(f"✅ **{count} کانفیگ شناسایی شد.**\n⬇️ در حال ثبت در دیتابیس...")
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            with db.get_connection() as (conn, cur):
                for i, cfg in enumerate(configs):
                    # دریافت نام و لینک از دیکشنری جدید
                    real_name = cfg.get('name', 'Unknown')
                    conf_link = cfg.get('link')
                    
                    # اگر نام نداشت، یک نام پیش‌فرض بساز
                    if real_name == "Unknown" or not real_name:
                        real_name = f"{sub_name}_{i + 1}"
                    
                    # تمیزکاری نام
                    real_name = urllib.parse.unquote(real_name).replace('+', ' ').strip()

                    cur.execute(
                        "INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score) VALUES (%s,'sub_item', %s,%s,%s,10)",
                        (uid, conf_link, real_name, now)
                    )
                conn.commit()

            await msg.edit_text(
                f"✅ **عملیات موفق!**\n"
                f"📂 نام مجموعه: `{sub_name}`\n"
                f"🔢 تعداد ثبت شده: `{count}` کانفیگ"
            )
            await asyncio.sleep(2)
            await start(update, context)
            return ConversationHandler.END

    except Exception as e:
        await msg.edit_text(f"❌ خطا در پردازش: {e}")
        return ConversationHandler.END

# ==============================================================================
