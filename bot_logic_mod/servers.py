"""
Auto-split module from original bot_logic.py
Section: servers
"""

from bot_logic_mod.base import *  # noqa

# 🛠 SERVER & GROUP MANAGEMENT
# ==============================================================================
async def groups_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    groups = db.get_user_groups(update.effective_user.id)
    reply_markup = keyboard.groups_menu_kb(groups)
    await safe_edit_message(update, "📂 Groups:", reply_markup=reply_markup)

async def add_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "📝 Name:", reply_markup=keyboard.get_cancel_markup())
    return GET_GROUP_NAME

async def get_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.add_group(update.effective_user.id, update.message.text)
    await start(update, context)
    return ConversationHandler.END

async def delete_group_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.delete_group(int(update.callback_query.data.split('_')[1]), update.effective_user.id)
    await groups_menu(update, context)

async def add_server_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    srv_count = len(db.get_all_user_servers(update.effective_user.id))
    if update.effective_user.id != SUPER_ADMIN_ID and srv_count >= user['server_limit']:
        await update.effective_message.reply_text("⛔️ **شما به سقف مجاز افزودن سرور رسیده‌اید.**")
        return ConversationHandler.END
    await safe_edit_message(update, "🏷 **نام سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_NAME

async def add_server_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    srv_count = len(db.get_all_user_servers(update.effective_user.id))
    if update.effective_user.id != SUPER_ADMIN_ID and srv_count >= user['server_limit']:
        await safe_edit_message(update, "⛔️ **شما به سقف مجاز افزودن سرور رسیده‌اید.**")
        return ConversationHandler.END
    reply_markup = keyboard.add_server_method_kb()
    txt = "➕ **افزودن سرور جدید**\n\nلطفاً روش مورد نظر خود را انتخاب کنید:\n\n1️⃣ **مرحله به مرحله:** ربات سوال می‌پرسد و شما پاسخ می‌دهید.\n2️⃣ **سریع (خطی):** تمام اطلاعات را در یک پیام می‌فرستید (مناسب برای افزودن همزمان چند سرور)."
    if update.callback_query: await safe_edit_message(update, txt, reply_markup=reply_markup)
    else: await update.message.reply_text(txt, reply_markup=reply_markup)
    return SELECT_ADD_METHOD

async def add_server_step_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🏷 **نام سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_NAME

async def add_server_linear_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    txt = "⚡️ **افزودن سریع سرورها**\n\nلطفاً مشخصات سرورها را به صورت **5 خطی** ارسال کنید.\nهر سرور باید دقیقاً در 5 خط زیر هم باشد:\n1. نام سرور\n2. آی‌پی\n3. پورت\n4. یوزرنیم\n5. پسورد\n\n⚠️ **نکته:** اگر چند سرور دارید، بلافاصله بعد از پسورد اولی، اطلاعات سرور دوم را شروع کنید.\n\n💡 **مثال:**\n`Server A`\n`192.168.1.1`\n`22`\n`root`\n`Pass123`\n`Server B`\n`45.33.22.11`\n`2244`\n`admin`\n`Secr3t`\n\n👇 اطلاعات را ارسال کنید:"
    await update.callback_query.message.reply_text(txt, reply_markup=keyboard.get_cancel_markup(), parse_mode='Markdown')
    return GET_LINEAR_DATA
async def process_linear_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش متن خطی با فرمت ۵ خطی (همراه با سیستم ضد بلاک اصلاح شده)"""
    text = update.message.text
    # حذف خطوط خالی اضافی
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    uid = update.effective_user.id
    user = db.get_user(uid)
    
    limit = user['server_limit']
    current_count = len(db.get_all_user_servers(uid))

    success = 0
    failed = 0
    report = []

    msg = await update.message.reply_text("⏳ **در حال پردازش، تست اتصال و ایمن‌سازی...**")

    # بررسی فرمت
    if len(lines) % 5 != 0:
        await msg.edit_text(
            f"❌ **فرمت ارسال اشتباه است!**\n\n"
            f"تعداد خطوط باید مضربی از ۵ باشد.\n"
            f"شما {len(lines)} خط فرستادید.\n\n"
            "لطفاً اصلاح کنید و مجدد ارسال نمایید."
        )
        return GET_LINEAR_DATA

    loop = asyncio.get_running_loop()

    # 1. دریافت آی‌پی ربات (یکبار برای همه)
    bot_public_ip = await loop.run_in_executor(EXECUTOR, ServerMonitor.get_bot_public_ip)

    # تبدیل ادمین آیدی به عدد برای اطمینان
    try: admin_id_int = int(SUPER_ADMIN_ID)
    except: admin_id_int = 0

    # پردازش ۵ خط به ۵ خط
    for i in range(0, len(lines), 5):
        name = lines[i]
        ip = lines[i + 1]
        port_str = lines[i + 2]
        username = lines[i + 3]
        password = lines[i + 4]

        # چک کردن لیمیت (فقط اگر کاربر ادمین نباشد)
        if uid != admin_id_int and (current_count + success) >= limit:
            report.append(f"⛔️ محدودیت پر شد! (سرور {name} نادیده گرفته شد)")
            failed += 1
            continue

        if not port_str.isdigit():
            report.append(f"⚠️ پورت نامعتبر برای {name}: `{port_str}`")
            failed += 1
            continue

        port = int(port_str)

        # تست اتصال
        res = await loop.run_in_executor(
            None, ServerMonitor.check_full_stats, ip, port, username, password
        )

        if res['status'] == 'Online':
            try:
                # ذخیره در دیتابیس
                data = {
                    'name': name, 'ip': ip, 'port': port,
                    'username': username, 'password': sec.encrypt(password),
                    'expiry_date': None
                }
                # ارسال شناسه ادمین برای دور زدن لیمیت در دیتابیس
                db.add_server(uid, 0, data, admin_id_int)

                # ✅ اجرای سیستم ضد بلاک (Anti-Block) - اصلاح شده
                if bot_public_ip:
                    # تعریف تابع همگام
                    def run_whitelist():
                        ServerMonitor.whitelist_bot_ip(ip, port, username, password, bot_public_ip)
                    
                    # تعریف یک رپر ناهمگام (Async Wrapper) برای create_task
                    async def background_whitelist():
                        await loop.run_in_executor(EXECUTOR, run_whitelist)
                    
                    # حالا می‌توانیم create_task کنیم چون یک Coroutine داریم
                    asyncio.create_task(background_whitelist())

                report.append(f"✅ **{name}**: افزوده و ایمن‌سازی شد.")

                # 📦 نصب/فعال‌سازی ایجنت مانیتورینگ (برای روشن شدن وب‌سوکت)
                try:
                    try:
                        await msg.edit_text(
                            f"⏳ **({success + failed + 1}/{len(lines)//5})** در حال نصب ایجنت روی **{name}**...",
                            parse_mode='Markdown'
                        )
                    except Exception:
                        pass

                    ok_agent, agent_msg = await loop.run_in_executor(
                        EXECUTOR,
                        ServerMonitor.install_agent_service,
                        ip,
                        port,
                        username,
                        password,
                        AGENT_PORT,
                    )
                    if ok_agent:
                        report.append(f"🟢 **{name}**: ایجنت نصب و فعال شد (WS:{AGENT_PORT}).")
                    else:
                        report.append(f"⚠️ **{name}**: سرور ذخیره شد، اما نصب ایجنت ناموفق بود: `{agent_msg}`")
                except Exception as e:
                    report.append(f"⚠️ **{name}**: خطای نصب ایجنت: `{e}`")

                success += 1
            except Exception as e:
                err_txt = str(e)
                if "duplicate key" in err_txt or "unique constraint" in err_txt:
                    report.append(f"❌ خطای تکراری: نام **{name}** قبلاً ثبت شده است.")
                elif "Server Limit Reached" in err_txt:
                    report.append(f"⛔️ محدودیت تعداد سرور پر شده است ({name}).")
                else:
                    report.append(f"❌ خطا در ذخیره {name}: {err_txt}")
                failed += 1
        else:
            report.append(f"🔴 عدم اتصال {name}: `{res.get('error', 'Unknown Error')}`")
            failed += 1

    final_txt = (
            f"📊 **نتیجه عملیات:**\n"
            f"✅ موفق: `{success}` | ❌ ناموفق: `{failed}`\n"
            f"➖➖➖➖➖➖➖➖\n" +
            "\n".join(report)
    )

    await msg.edit_text(final_txt, parse_mode='Markdown')
    await asyncio.sleep(3)
    await start(update, context)
    return ConversationHandler.END
async def get_srv_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv'] = {'name': update.message.text}
    await update.message.reply_text("🌐 **آدرس IP سرور را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_IP


async def get_srv_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv']['ip'] = update.message.text
    await update.message.reply_text("🔌 **پورت SSH را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_PORT


async def get_srv_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['srv']['port'] = int(update.message.text)
    except:
        await update.message.reply_text("❌ فقط عدد وارد کنید.")
        return GET_PORT
    await update.message.reply_text("👤 **نام کاربری (Username) را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_USER


async def get_srv_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv']['username'] = update.message.text
    await update.message.reply_text("🔑 **رمز عبور (Password) را وارد کنید:**", reply_markup=keyboard.get_cancel_markup(),
                                    parse_mode='Markdown')
    return GET_PASS


async def get_srv_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['srv']['password'] = sec.encrypt(update.message.text)
    # تایید پورت وب‌سوکت از روی کانفیگ (قبل از ادامه)
    await update.message.reply_text(
        f"🔌 **تایید پورت وب‌سوکت ایجنت**\n\n"
        f"پورت ایجنت طبق تنظیمات سیستم: `{AGENT_PORT}`\n"
        "آیا این پورت روی سرور باز و آزاد است؟\n\n"
        "(بدون تایید، فرآیند افزودن ادامه پیدا نمی‌کند)",
        reply_markup=keyboard.ws_port_confirm_kb(),
        parse_mode='Markdown'
    )
    return CONFIRM_WS_PORT


async def confirm_ws_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm default WS port or ask for a custom one."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "ws_port_ok":
        context.user_data['srv']['ws_port'] = int(AGENT_PORT)
        await query.edit_message_text(
            f"✅ پورت پیش‌فرض انتخاب شد: {int(AGENT_PORT)}\n\n📅 حالا تاریخ انقضا را وارد کنید (مثلاً 2026-01-01):"
        )
        return GET_EXPIRY

    # ws_port_no => custom port
    await query.edit_message_text(
        "🔧 لطفاً پورت WebSocket ایجنت را وارد کنید (مثلاً 8081).\n"
        "⚠️ این پورت باید روی همه سرورها آزاد باشد و در فایروال مسدود نشده باشد."
    )
    return GET_CUSTOM_WS_PORT




async def get_srv_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        if days > 0:
            expiry_dt = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            context.user_data['srv']['expiry_date'] = expiry_dt
            msg = f"✅ تاریخ انقضا تنظیم شد: {days} روز دیگر."
        else:
            context.user_data['srv']['expiry_date'] = None
            msg = "♾ سرور به عنوان نامحدود ثبت شد."
    except:
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید (مثلا 30).")
        return GET_EXPIRY

    # استفاده از ماژول کیبورد (برای select_group_kb که لیست برمی‌گرداند)
    group_kb_list = await get_group_keyboard(update.effective_user.id)
    
    await update.message.reply_text(f"{msg}\n\n📂 **حالا سرور در کدام پوشه ذخیره شود؟**",
                                    reply_markup=InlineKeyboardMarkup(group_kb_list),
                                    parse_mode='Markdown')
    return SELECT_GROUP


async def get_group_keyboard(uid):
    groups = db.get_user_groups(uid)
    return keyboard.select_group_kb(groups)


async def select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره نهایی سرور و اجرای وایت‌لیست"""
    if update.callback_query.data == 'cancel_flow': return await cancel_handler_func(update, context)
    
    await safe_edit_message(update, "⚡️ **در حال تست اتصال و ایمن‌سازی سرور...**")
    
    data = context.user_data['srv']
    loop = asyncio.get_running_loop()
    
    # تست اتصال
    res = await loop.run_in_executor(EXECUTOR, ServerMonitor.check_full_stats, data['ip'], data['port'], data['username'], sec.decrypt(data['password']))
    
    if res['status'] == 'Online':
        try:
            # ذخیره در دیتابیس
            # 👇 اصلاح مهم: ارسال SUPER_ADMIN_ID به عنوان آرگومان چهارم
            db.add_server(update.effective_user.id, int(update.callback_query.data), data, SUPER_ADMIN_ID)
            
            # ✅ اجرای سیستم ضد بلاک (Anti-Block)
            try:
                bot_ip = await loop.run_in_executor(EXECUTOR, ServerMonitor.get_bot_public_ip)
                if bot_ip:
                    # اجرا در پس‌زمینه
                    def run_whitelist():
                        ServerMonitor.whitelist_bot_ip(data['ip'], data['port'], data['username'], sec.decrypt(data['password']), bot_ip)
                    
                    async def _bg_whitelist():
                        await loop.run_in_executor(EXECUTOR, run_whitelist)

                    asyncio.create_task(_bg_whitelist())
            except Exception as e:
                logger.error(f"Whitelist Error on Add: {e}")

            # ✅ پیام موفقیت + نصب و فعال‌سازی ایجنت با SSH (طبق منطق پروژه)
            status_msg = await update.callback_query.message.reply_text(
                "✅ **اتصال موفق! سرور ذخیره و وایت‌لیست شد.**\n\n"
                "📦 **در حال نصب/فعال‌سازی ایجنت مانیتورینگ...**\n"
                "(این مرحله وب‌سوکت را روی سرور روشن می‌کند)",
                parse_mode='Markdown'
            )

            # نمایش پیشرفت گرافیکی (Spinner + Bar)
            running = True

            async def _progress_ui():
                frames = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
                step = 0
                while running:
                    step += 1
                    fill = step % 11
                    bar = "█" * fill + "░" * (10 - fill)
                    try:
                        await status_msg.edit_text(
                            "✅ **اتصال موفق! سرور ذخیره و وایت‌لیست شد.**\n\n"
                            f"{frames[step % len(frames)]} **نصب ایجنت در حال انجام است...**\n"
                            f"`[{bar}]`",
                            parse_mode='Markdown'
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)

            ui_task = asyncio.create_task(_progress_ui())
            try:
                ok_agent, agent_msg = await loop.run_in_executor(
                    EXECUTOR,
                    ServerMonitor.install_agent_service,
                    data['ip'],
                    data['port'],
                    data['username'],
                    sec.decrypt(data['password']),
                    AGENT_PORT,
                )
            finally:
                running = False
                try:
                    await ui_task
                except Exception:
                    pass

            if ok_agent:
                try:
                    await status_msg.edit_text(
                        "✅ **ایجنت با موفقیت نصب و فعال شد.**\n"
                        f"🔌 پورت وب‌سوکت: `{AGENT_PORT}`\n\n"
                        "حالا می‌توانید از دکمه «وضعیت سرور» استفاده کنید.",
                        parse_mode='Markdown'
                    )
                except Exception:
                    pass
            else:
                # سرور ذخیره شده، اما ایجنت نصب نشده (لاگ و اطلاع)
                logger.error(f"Agent install failed on {data['ip']}:{AGENT_PORT} -> {agent_msg}")
                try:
                    await status_msg.edit_text(
                        "⚠️ **سرور ذخیره شد، اما نصب ایجنت با خطا مواجه شد.**\n\n"
                        f"❌ خطا: `{agent_msg}`\n\n"
                        "برای رفع مشکل، از منوی سرور گزینه «آپدیت/نصب ایجنت» را اجرا کنید.",
                        parse_mode='Markdown'
                    )
                except Exception:
                    pass

        except Exception as e:
            await update.callback_query.message.reply_text(f"❌ خطا در ذخیره: {e}")
    else:
        await update.callback_query.message.reply_text(f"❌ **عدم اتصال به سرور!**\n\n⚠️ خطا: `{res['error']}`", parse_mode='Markdown')
        
    await start(update, context)
    return ConversationHandler.END

async def list_groups_for_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
    except:
        pass
    groups = db.get_user_groups(update.effective_user.id)
    
    # استفاده از ماژول کیبورد
    reply_markup = keyboard.group_selection_kb(groups)
    
    await safe_edit_message(update, "🗂 **پوشه مورد نظر را انتخاب کنید:**", reply_markup=reply_markup)


async def show_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
    except:
        pass
    uid, data = update.effective_user.id, update.callback_query.data
    # ذخیره اسکوپ نمایش برای عملیات‌های بعدی مثل حذف دسته‌جمعی
    context.user_data['last_server_list_scope'] = data

    servers = db.get_all_user_servers(uid) if data == 'list_all' else db.get_servers_by_group(uid, int(
        data.split('_')[1]))
    if not servers:
        try:
            await update.callback_query.answer("⚠️ این پوشه خالی است!", show_alert=True)
        except:
            pass
        return
    
    # ذخیره شناسه‌ها برای عملیات‌های بعدی
    context.user_data['last_server_list_ids'] = [s['id'] for s in servers]

    reply_markup = keyboard.server_list_kb(servers)
    
    await safe_edit_message(update, "🖥 **لیست سرورها:**", reply_markup=reply_markup)


# ==============================================================================
# 🗑 MULTI-DELETE (حذف دسته‌جمعی سرورها)
# ==============================================================================

def _build_multidel_kb(servers, selected_ids):
    kb = []
    for s in servers:
        checked = "✅" if s['id'] in selected_ids else "⬜️"
        kb.append([InlineKeyboardButton(f"{checked} {s['name']}  |  {s['ip']}", callback_data=f"srv_multidel_toggle_{s['id']}")])
    kb.append([InlineKeyboardButton("🗑 تایید حذف", callback_data='srv_multidel_confirm')])
    kb.append([InlineKeyboardButton("🔙 انصراف", callback_data='srv_multidel_cancel')])
    return InlineKeyboardMarkup(kb)


async def srv_multidel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع حذف دسته‌جمعی از لیست فعلی."""
    try:
        await update.callback_query.answer()
    except Exception:
        pass

    uid = update.effective_user.id
    # اگر لیست قبلی در user_data نیست، از همه سرورها استفاده می‌کنیم
    scope = context.user_data.get('last_server_list_scope', 'list_all')
    if scope == 'list_all':
        servers = db.get_all_user_servers(uid)
    else:
        try:
            gid = int(str(scope).split('_')[1])
        except Exception:
            gid = 0
        servers = db.get_servers_by_group(uid, gid)

    if not servers:
        try:
            await update.callback_query.answer("⚠️ لیستی برای حذف وجود ندارد", show_alert=True)
        except Exception:
            pass
        return

    context.user_data['multidel_selected'] = set()
    context.user_data['multidel_scope'] = scope
    await safe_edit_message(
        update,
        "🗑 **حذف دسته‌جمعی**\n\n"
        "روی سرورها تپ کنید تا انتخاب شوند، سپس \"تایید حذف\" را بزنید.",
        reply_markup=_build_multidel_kb(servers, context.user_data['multidel_selected']),
    )


async def srv_multidel_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    uid = update.effective_user.id
    try:
        sid = int(q.data.split('_')[-1])
    except Exception:
        return

    selected = context.user_data.get('multidel_selected')
    if not isinstance(selected, set):
        selected = set()
    if sid in selected:
        selected.remove(sid)
    else:
        selected.add(sid)
    context.user_data['multidel_selected'] = selected

    scope = context.user_data.get('multidel_scope', 'list_all')
    if scope == 'list_all':
        servers = db.get_all_user_servers(uid)
    else:
        try:
            gid = int(str(scope).split('_')[1])
        except Exception:
            gid = 0
        servers = db.get_servers_by_group(uid, gid)

    await safe_edit_message(
        update,
        "🗑 **حذف دسته‌جمعی**\n\n"
        "روی سرورها تپ کنید تا انتخاب شوند، سپس \"تایید حذف\" را بزنید.",
        reply_markup=_build_multidel_kb(servers, selected),
    )


async def srv_multidel_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    uid = update.effective_user.id
    selected = context.user_data.get('multidel_selected')
    if not selected:
        try:
            await q.answer("هیچ موردی انتخاب نشده", show_alert=True)
        except Exception:
            pass
        return

    # حذف
    deleted = 0
    for sid in list(selected):
        try:
            db.delete_server(int(sid), uid)
            deleted += 1
        except Exception:
            pass

    context.user_data.pop('multidel_selected', None)
    scope = context.user_data.pop('multidel_scope', 'list_all')
    try:
        await q.answer(f"✅ {deleted} سرویس حذف شد", show_alert=True)
    except Exception:
        pass

    # بازگشت به لیست همان اسکوپ
    update.callback_query.data = scope
    await show_servers(update, context)


async def srv_multidel_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer("انصراف")
    except Exception:
        pass
    scope = context.user_data.pop('multidel_scope', None) or context.user_data.get('last_server_list_scope', 'list_all')
    update.callback_query.data = scope
    await show_servers(update, context)
# ==============================================================================
# 📊 MONITORING & SERVER ACTIONS
# ==============================================================================
async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await status_dashboard(update, context)

async def status_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """داشبورد اصلی با رابط کاربری گرافیکی و تفکیک شده"""
    if update.callback_query:
        try: await update.callback_query.answer()
        except: pass
    
    user = update.effective_user
    j_date = get_jalali_str()
    
    txt = (
        f"📊 **داشبورد مدیریتی سونار**\n"
        f"👤 کاربر: {user.full_name}\n"
        f"📅 تاریخ: `{j_date}`\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"یکی از بخش‌های زیر را برای مشاهده وضعیت انتخاب کنید:"
    )
    
    # استفاده از ماژول کیبورد
    reply_markup = keyboard.dashboard_main_kb()
    
    await safe_edit_message(update, txt, reply_markup=reply_markup)

# این تابع جدید برای نمایش وضعیت سرورهاست (جایگزین لاجیک قبلی در داشبورد)
async def show_server_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    
    # 1. ارسال پیام انتظار
    msg = await safe_edit_message(update, "🔄 **در حال دریافت وضعیت تمام سرورها...**\n(این عملیات در پس‌زمینه انجام می‌شود)")
    if not msg and query: msg = query.message

    # 2. تعریف ورکر پس‌زمینه
    async def background_stats_worker():
        async with GLOBAL_SEMAPHORE: # رعایت صف ۵۰ تایی
            try:
                servers = db.get_all_user_servers(uid)
                if not servers:
                    await msg.edit_text("❌ سروری یافت نشد.", reply_markup=keyboard.dashboard_main_kb())
                    return

                loop = asyncio.get_running_loop()
                tasks = []
                # ساخت تسک‌ها برای هر سرور (اجرای واقعی همزمان)
                for s in servers:
                    if s['is_active']:
                        tasks.append(
                            StatsManager.check_full_stats(
                                s['ip'], s['port'], s['username'], sec.decrypt(s['password'])
                            )
                        )
                    else:
                        # سرور غیرفعال
                        tasks.append(asyncio.sleep(0, result={'status': 'Disabled'}))
                
                # اجرای همزمان همه چک‌ها
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # ساخت متن گزارش
                txt = f"🖥 **وضعیت سرورهای شما**\n➖➖➖➖➖➖➖➖➖➖\n\n"
                for i, final_res in enumerate(results):
                    srv = servers[i]
                    if isinstance(final_res, Exception):
                        txt += f"🔴 **{srv['name']}** | Error\n"
                        continue
                    if final_res.get('status') == 'Online':
                        txt += f"🟢 **{srv['name']}** | CPU: {final_res.get('cpu', 0)}%\n"
                    elif final_res.get('status') == 'Disabled':
                        txt += f"⚪️ **{srv['name']}** | Disabled\n"
                    else:
                        txt += f"🔴 **{srv['name']}** | Offline\n"

                reply_markup = keyboard.server_stats_kb()
                await msg.edit_text(txt, reply_markup=reply_markup, parse_mode='Markdown')

            except Exception as e:
                try: await msg.edit_text(f"❌ خطا: {e}")
                except: pass

    # 3. اجرا در پس‌زمینه
    asyncio.create_task(background_stats_worker())

async def server_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_sid=None):
    """نمایش جزئیات سرور (نسخه کاملاً غیرهمگام - Non-Blocking)"""

    query = update.callback_query if update.callback_query else None
    if query:
        try:
            await query.answer()
        except Exception:
            pass

    # ✅ اولویت قطعی با custom_sid
    sid = custom_sid
    if sid is None and query:
        parts = str(query.data).split('_')
        sid = None
        for p in parts:
            if str(p).isdigit():
                sid = int(p)
                break

    if sid is None:
        return

    # ✅ اطمینان از int بودن
    try:
        sid = int(sid)
    except Exception:
        if query:
            await query.message.reply_text("❌ شناسه سرور نامعتبر است.")
        return


    # 2. بارگذاری اطلاعات سرور + پیام اولیه
    srv = db.get_server_by_id(sid)
    if not srv:
        await safe_edit_message(update, f"❌ سرور با ID={sid} پیدا نشد")
        return

    msg = await safe_edit_message(update, "⏳ در حال دریافت اطلاعات از Agent (WebSocket)...")

    # 3. تعریف تابع پردازش سنگین (Worker)
    async def heavy_process_task():
        async with GLOBAL_SEMAPHORE:
            try:
                res = await ServerMonitor.check_full_stats_ws(srv['ip'], AGENT_PORT, sec.decrypt(srv['password']))
                
                # ✅ اصلاح: محاسبه هوشمند آپتایم (اگر ایجنت قدیمی بود)
                uptime = res.get('uptime_str')
                if not uptime and res.get('uptime_sec'):
                    # تبدیل ثانیه به فرمت خوانا
                    uptime = str(timedelta(seconds=int(res['uptime_sec'])))
                if not uptime:
                    uptime = "⚠️ نامعلوم (نیاز به آپدیت ایجنت)"

                reply_markup = keyboard.server_detail_kb(sid, srv['ip'], True)

                if res['status'] == 'Online':
                    db.update_status(sid, "Online")
                    
                    # رند کردن اعداد
                    cpu_val = round(res.get('cpu', 0), 1)
                    ram_val = round(res.get('ram', 0), 1)
                    
                    cpu_emoji = "🟢" if cpu_val < 50 else "🔴"
                    txt = (
                        f"🟢 **{srv['name']}** `[Online]`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🌐 IP: `{srv['ip']}`\n"
                        f"📊 CPU: {cpu_emoji} `{cpu_val}%`\n"
                        f"💾 RAM: `{ram_val}%`\n"
                        f"🔌 Uptime: `{uptime}`\n"
                    )
                else:
                    err = str(res.get('error', 'Connect Fail'))
                    # اگر احراز هویت اشتباه باشد، وضعیت جداگانه ثبت شود
                    if err.lower().find('auth') != -1:
                        db.update_status(sid, "Auth Failed")
                    else:
                        db.update_status(sid, "Offline")
                    db.update_server_error(sid, err)
                    txt = f"🔴 **{srv['name']}** `[Offline]`\n❌ خطا: `{err}`"

                try: await msg.edit_text(txt, reply_markup=reply_markup, parse_mode='Markdown')
                except: await context.bot.send_message(chat_id=update.effective_chat.id, text=txt, reply_markup=reply_markup, parse_mode='Markdown')

            except Exception as e:
                logger.error(f"Task Error: {e}")
                try: await msg.edit_text(f"❌ خطا: {e}")
                except: pass

    # 4. اجرا در پس‌زمینه (Non-Blocking)
    asyncio.create_task(heavy_process_task())

async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    parts = data.split('_')
    # ر... handle incorrect order so we never query id='cleandisk'
    act = ''
    sid = None
    try:
        if len(parts) >= 3 and str(parts[2]).isdigit():
            act, sid = parts[1], int(parts[2])
        elif len(parts) >= 3 and str(parts[1]).isdigit():
            sid = int(parts[1])
            act = parts[2]
        else:
            # last resort: find any numeric part
            for p in parts:
                if str(p).isdigit():
                    sid = int(p)
                    break
            act = parts[1] if len(parts) > 1 else ''
    except Exception:
        sid = None

    if sid is None:
        try:
            await update.callback_query.answer("❌ شناسه سرور نامعتبر", show_alert=True)
        except Exception:
            pass
        return

    srv = db.get_server_by_id(sid)
    if not srv:
        try:
            await update.callback_query.answer("❌ سرور یافت نشد!", show_alert=True)
        except:
            pass
        return

    uid = update.effective_user.id
    user = db.get_user(uid)
    is_premium = True if user['plan_type'] == 1 or uid == SUPER_ADMIN_ID else False

    LOCKED_FEATURES = ['installscript']

    if act in LOCKED_FEATURES and not is_premium:
        try:
            await update.callback_query.answer("🔒 این قابلیت مخصوص کاربران پریمیوم است!", show_alert=True)
        except:
            pass
        return

    if srv['password']:
        real_pass = sec.decrypt(srv['password'])
    else:
        real_pass = ""

    loop = asyncio.get_running_loop()

    if act == 'del':
        db.delete_server(sid, update.effective_user.id)
        try:
            await update.callback_query.answer("✅ سرور با موفقیت حذف شد.")
        except:
            pass
        await list_groups_for_servers(update, context)

    elif act == 'reboot':
        try:
            await update.callback_query.answer("⚠️ دستور ریبوت ارسال شد.")
        except:
            pass
        # عملیات اجرایی در پس‌زمینه (بدون بلاک کردن ربات)
        async def do_reboot():
            try:
                await ServerMonitor.run_remote_command(
                    srv['ip'], srv['port'], srv['username'], real_pass, "reboot", timeout=20
                )
            except Exception as e:
                logger.error(f"Reboot Error: {e}")

        asyncio.create_task(do_reboot())
    elif act == 'editexpiry':
        await edit_expiry_start(update, context)

    elif act == 'fullreport':
        wait_msg = await update.callback_query.message.reply_text(
            "⏳ **در حال آنالیز جامع وضعیت سرور...**\n\n"
            "1️⃣ استعلام دیتاسنتر...\n"
            "2️⃣ پینگ جهانی (۱۰ ثانیه زمان می‌برد)..."
        )
        # 👇 اصلاح شد: استفاده از StatsManager برای اطلاعات آماری
        task_dc = loop.run_in_executor(EXECUTOR, StatsManager.get_datacenter_info, srv['ip'])
        task_ch = loop.run_in_executor(EXECUTOR, StatsManager.check_host_api, srv['ip'])

        (dc_ok, dc_data), (ch_ok, ch_data) = await asyncio.gather(task_dc, task_ch)

        if dc_ok:
            infra_txt = (
                f"🏢 **زیرساخت (Infrastructure):**\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"🏳️ **کشور:** {dc_data['country_name']} ({dc_data['country_code2']})\n"
                f"🏢 **دیتاسنتر:** `{dc_data['isp']}`\n"
                f"🔢 **آی‌پی:** `{dc_data['ip_number']}`\n"
            )
        else:
            infra_txt = f"❌ خطا در دریافت اطلاعات دیتاسنتر: {dc_data}\n"

        if ch_ok:
            # 👇 اصلاح شد: استفاده از StatsManager
            ping_txt = StatsManager.format_full_global_results(ch_data)
        else:
            ping_txt = f"❌ خطا در Check-Host API: {ch_data}"

        final_report = (
            f"📊 **گزارش جامع سرور: {srv['name']}**\n"
            f"📅 {get_jalali_str()}\n\n"
            f"{infra_txt}\n"
            f"🌍 **وضعیت پینگ جهانی:**\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"{ping_txt}"
        )
        await wait_msg.delete()
        await update.callback_query.message.reply_text(final_report, parse_mode='Markdown')

    elif act == 'chart':
        await update.callback_query.message.reply_text("📊 **در حال ترسیم نمودار...**")
        stats = await loop.run_in_executor(EXECUTOR, db.get_server_stats, sid)
        if not stats:
            await update.callback_query.message.reply_text("❌ داده‌ای برای رسم نمودار موجود نیست.")
            return
        
        # تولید نمودار نیازی به وب‌سوکت ندارد، پس در Executor اجرا می‌شود
        photo = await loop.run_in_executor(EXECUTOR, StatsManager.generate_plot, srv['name'], stats)
        if photo:
            await update.callback_query.message.reply_photo(photo=photo, caption=f"📊 مصرف منابع: **{srv['name']}**")
        else:
            await update.callback_query.message.reply_text("❌ خطا در تولید تصویر نمودار.")

    elif act == 'datacenter':
        await update.callback_query.message.reply_text("🔍 **در حال استعلام...**")
        # استعلام دیتاسنتر از API خارجی است و نیازی به SSH ندارد
        ok, data = await loop.run_in_executor(EXECUTOR, StatsManager.get_datacenter_info, srv['ip'])
        if ok:
            txt = (
                f"🏢 **مشخصات دیتاسنتر:**\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"🖥 **آی‌پی:** `{data['ip']}`\n"
                f"🌍 **کشور:** {data['country_name']} ({data['country_code2']})\n"
                f"🏢 **کمپانی:** `{data['isp']}`\n"
                f"✅ **وضعیت:** {data['response_message']}"
            )
            await update.callback_query.message.reply_text(txt, parse_mode='Markdown')
        else:
            await update.callback_query.message.reply_text(f"❌ خطا: `{data}`", parse_mode='Markdown')

    elif act == 'checkhost':
        await update.callback_query.message.reply_text("🌍 **در حال دریافت گزارش Check-Host...**")
        # استعلام CheckHost از API خارجی است و نیازی به SSH ندارد
        ok, data = await loop.run_in_executor(EXECUTOR, StatsManager.check_host_api, parts[3])
        report = StatsManager.format_check_host_results(data) if ok else f"❌ خطا: {data}"
        await update.callback_query.message.reply_text(report, parse_mode='Markdown')

    elif act == 'speedtest':
        await update.callback_query.message.reply_text(
            "🚀 **تست سرعت آغاز شد...**\n(نتیجه پس از پایان ارسال می‌شود، می‌توانید به کارهای دیگر برسید)")
        
        # ✅ اصلاح شده: استفاده از Async Wrapper برای وب‌سوکت
        async def do_speedtest():
            ok, out = await ServerMonitor.run_speedtest(srv['ip'], srv['port'], srv['username'], real_pass)
            await context.bot.send_message(update.effective_chat.id, f"🚀 نتیجه تست سرعت:\n\n{out}")
        
        asyncio.create_task(do_speedtest())

    elif act == 'installspeed':
        await update.callback_query.message.reply_text("📥 **نصب ابزار Speedtest در پس‌زمینه آغاز شد...**")
        
        # ✅ اصلاح شده: استفاده از Async Wrapper برای وب‌سوکت
        async def do_install_speed():
            await ServerMonitor.install_speedtest(srv['ip'], srv['port'], srv['username'], real_pass)
            await context.bot.send_message(update.effective_chat.id, "✅ نصب Speedtest انجام شد.")
            
        asyncio.create_task(do_install_speed())

    elif act == 'repoupdate':
        await update.callback_query.message.reply_text(
            "📦 **آپدیت مخازن در حال انجام است...**\n(لطفاً صبور باشید، نتیجه ارسال می‌شود)")
        
        # ✅ اصلاح شده: استفاده از Async Wrapper برای وب‌سوکت
        async def do_repo_update():
            ok, out = await ServerMonitor.repo_update(srv['ip'], srv['port'], srv['username'], real_pass)
            status = "✅" if ok else "❌"
            await context.bot.send_message(update.effective_chat.id, f"{status} نتیجه آپدیت مخازن:\n{out}")
            
        asyncio.create_task(do_repo_update())

    elif act == 'fullupdate':
        await update.callback_query.message.reply_text(
            "💎 **آپدیت کامل سیستم آغاز شد!**\n⚠️ این عملیات ممکن است ۱۰ تا ۲۰ دقیقه زمان ببرد.\nنتیجه پس از پایان ارسال خواهد شد.")
        
        # ✅ اصلاح شده: استفاده از Async Wrapper برای وب‌سوکت
        async def do_full_update():
            ok, out = await ServerMonitor.full_system_update(srv['ip'], srv['port'], srv['username'], real_pass)
            status = "✅" if ok else "❌"
            await context.bot.send_message(update.effective_chat.id, f"{status} نتیجه آپدیت کامل:\n{out}")
            
        asyncio.create_task(do_full_update())

    elif act == 'clearcache':
        try:
            await update.callback_query.answer("🧹 کش رم پاکسازی شد.")
        except:
            pass
        
        # ✅ اصلاح شده: فراخوانی مستقیم تابع Async
        await ServerMonitor.clear_cache(srv['ip'], srv['port'], srv['username'], real_pass)
        await server_detail(update, context)

    elif act == 'cleandisk':
        await update.callback_query.message.reply_text(
            "🧹 **پاکسازی دیسک آغاز شد...**\n"
            "این عملیات شامل حذف:\n"
            "- پکیج‌های بلااستفاده (Autoremove)\n"
            "- کش پکیج‌ها (Apt Clean)\n"
            "- لاگ‌های قدیمی (Journalctl)\n"
            "- فایل‌های موقت (Tmp)\n\n"
            "⏳ لطفاً صبر کنید..."
        )
        
        # ✅ اصلاح شده: فراخوانی مستقیم تابع Async و دریافت خروجی
        ok, result = await ServerMonitor.clean_disk_space(srv['ip'], srv['port'], srv['username'], real_pass)
        
        if ok:
            await update.callback_query.message.reply_text(
                f"✅ **پاکسازی با موفقیت انجام شد.**\n💾 نتیجه: `{result}`", parse_mode='Markdown')
        else:
            await update.callback_query.message.reply_text(f"❌ خطا در پاکسازی:\n{result}")
        await server_detail(update, context)

    elif act == 'dns':
        # استفاده از ماژول کیبورد
        reply_markup = keyboard.dns_selection_kb(sid)
        
        await safe_edit_message(update,
                                "⚙️ **تنظیم DNS سرور:**\nلطفاً پرووایدر مورد نظر را انتخاب کنید.\n(پس از انتخاب، اتصال اینترنت سرور با DNS جدید برقرار می‌شود)",
                                reply_markup=reply_markup)

    elif act == 'locked_terminal':
        try:
            await update.callback_query.answer("🔒 ترمینال مخصوص کاربران پریمیوم است.\nبرای دسترسی ارتقا دهید.",
                                               show_alert=True)
        except:
            pass

    elif act == 'installscript':
        await update.callback_query.answer("🔄 در حال اتصال و آپدیت...", cache_time=1)
        wait_msg = await update.callback_query.message.reply_text("⏳ **در حال آپدیت فایل مانیتورینگ روی سرور مقصد...**\n(این کار باعث نمایش دقیق آپتایم و ترافیک می‌شود)")
        
        # نصب مجدد ایجنت جدید روی سرور مقصد
        ok, msg = await loop.run_in_executor(EXECUTOR, ServerMonitor.install_agent_service, srv['ip'], srv['port'], srv['username'], real_pass, AGENT_PORT)
        
        if ok:
            await wait_msg.edit_text("✅ **ایجنت با موفقیت آپدیت شد.**\nاکنون دکمه «وضعیت سرور» را بزنید تا اطلاعات دقیق نمایش داده شود.")
        else:
            await wait_msg.edit_text(f"❌ خطا در آپدیت:\n{msg}")
async def set_config_cron_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره تنظیمات زمان‌بندی کانفیگ"""
    query = update.callback_query
    minutes = query.data.split('_')[1]
    
    db.set_setting(update.effective_user.id, 'config_report_interval', minutes)
    
    msg = "✅ گزارش کانفیگ غیرفعال شد." if minutes == '0' else f"✅ تنظیم شد: هر {minutes} دقیقه."
    try: await query.answer(msg, show_alert=True)
    except: pass
    
    await config_cron_menu(update, context)

async def set_cron_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.set_setting(update.effective_user.id, 'report_interval', int(update.callback_query.data.split('_')[1]))
    try:
        await update.callback_query.answer("ذخیره شد.")
    except:
        pass
    await settings_cron_menu(update, context)


async def resource_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی تنظیم آستانه مصرف منابع"""
    uid = update.effective_user.id
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass

    cpu_limit = db.get_setting(uid, 'cpu_threshold') or '80'
    ram_limit = db.get_setting(uid, 'ram_threshold') or '80'
    disk_limit = db.get_setting(uid, 'disk_threshold') or '90'

    txt = (
        "🎚 **تنظیم آستانه حساسیت (Thresholds)**\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "اگر مصرف منابع سرور از مقادیر زیر بیشتر شود، ربات هشدار می‌دهد.\n\n"
        f"🧠 **حداکثر CPU مجاز:** `{cpu_limit}%`\n"
        f"💾 **حداکثر RAM مجاز:** `{ram_limit}%`\n"
        f"💿 **حداکثر DISK مجاز:** `{disk_limit}%`"
    )

    # استفاده از ماژول کیبورد
    reply_markup = keyboard.resource_limits_kb(cpu_limit, ram_limit, disk_limit)

    await safe_edit_message(update, txt, reply_markup=reply_markup)


async def toggle_down_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.set_setting(update.effective_user.id, 'down_alert_enabled', update.callback_query.data.split('_')[2])
    await schedules_settings_menu(update, context)


async def ask_cpu_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "🧠 **حداکثر درصد مجاز CPU (0-100):**", reply_markup=keyboard.get_cancel_markup())
    return GET_CPU_LIMIT


async def save_cpu_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if 1 <= val <= 100:
            db.set_setting(update.effective_user.id, 'cpu_threshold', val)
            await update.message.reply_text(f"✅ ذخیره شد: {val}%")
            await resource_settings_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر.")
    return GET_CPU_LIMIT


async def ask_ram_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "💾 **حداکثر درصد مجاز RAM (0-100):**", reply_markup=keyboard.get_cancel_markup())
    return GET_RAM_LIMIT


async def save_ram_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if 1 <= val <= 100:
            db.set_setting(update.effective_user.id, 'ram_threshold', val)
            await update.message.reply_text(f"✅ ذخیره شد: {val}%")
            await resource_settings_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر.")
    return GET_RAM_LIMIT


async def ask_disk_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "💿 **حداکثر درصد مجاز Disk (0-100):**", reply_markup=keyboard.get_cancel_markup())
    return GET_DISK_LIMIT


async def save_disk_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if 1 <= val <= 100:
            db.set_setting(update.effective_user.id, 'disk_threshold', val)
            await update.message.reply_text(f"✅ ذخیره شد: {val}%")
            await resource_settings_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر.")
    return GET_DISK_LIMIT


async def ask_custom_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(update, "✍️ **بازه زمانی (دقیقه) را وارد کنید:**", reply_markup=keyboard.get_cancel_markup())
    return GET_CUSTOM_INTERVAL


async def set_custom_interval_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text)
        if 10 <= minutes <= 1440:
            db.set_setting(update.effective_user.id, 'report_interval', minutes * 60)
            await update.message.reply_text(f"✅ تنظیم شد: هر {minutes} دقیقه.")
            await settings_cron_menu(update, context)
            return ConversationHandler.END
    except:
        pass
    await update.message.reply_text("❌ عدد نامعتبر (بین 10 تا 1440).")
    return GET_CUSTOM_INTERVAL


async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_edit_message(
        update,
        "📝 **افزودن کانال جدید**\n\n"
        "لطفاً **آیدی عددی کانال** را ارسال کنید.\n"
        "مثال: `-100123456789`\n\n"
        "⚠️ **نکته:** ابتدا ربات را در کانال **ادمین** کنید.",
        reply_markup=keyboard.get_cancel_markup()
    )
    return GET_CHANNEL_FORWARD


async def get_channel_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message
        text = getattr(msg, 'text', '').strip()

        # اعتبارسنجی: آیدی باید با -100 شروع شود یا @ داشته باشد
        if not text or (not text.startswith('-100') and not text.startswith('@')):
            await msg.reply_text(
                "❌ **فرمت نامعتبر!**\n\n"
                "لطفاً فقط **آیدی عددی** (شروع با -100) یا **یوزرنیم** (شروع با @) بفرستید.\n"
                "مثال صحیح: `-100123456789`"
            )
            return GET_CHANNEL_FORWARD

        c_id = text
        c_name = "Channel (Manual)"

        # تلاش برای گرفتن اسم کانال جهت اطمینان
        try:
            chat = await context.bot.get_chat(c_id)
            c_name = chat.title
            c_id = str(chat.id)  # تبدیل نهایی به آیدی عددی
        except Exception as e:
            # اگر ربات ادمین نباشد یا آیدی غلط باشد
            await msg.reply_text(
                f"❌ **ربات نتوانست کانال را پیدا کند!**\n\n"
                f"1️⃣ مطمئن شوید آیدی `{text}` صحیح است.\n"
                f"2️⃣ مطمئن شوید ربات در کانال **ادمین** است.\n"
                f"خطا: {e}"
            )
            return GET_CHANNEL_FORWARD

        context.user_data['new_chan'] = {'id': c_id, 'name': c_name}

        kb = [
            [InlineKeyboardButton("🔥 فقط فشار منابع (CPU/RAM)", callback_data='type_resource')],
            [InlineKeyboardButton("🚨 فقط هشدار قطعی", callback_data='type_down'), InlineKeyboardButton("⏳ فقط انقضا", callback_data='type_expiry')],
            [InlineKeyboardButton("📊 فقط گزارشات", callback_data='type_report'), InlineKeyboardButton("✅ همه موارد", callback_data='type_all')]
        ]

        await msg.reply_text(
            f"✅ کانال **{c_name}** شناسایی شد.\n🆔 آیدی: `{c_id}`\n\n🛠 **این کانال برای دریافت چه نوع پیام‌هایی استفاده شود؟**",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return GET_CHANNEL_TYPE

    except Exception as e:
        logger.error(f"Channel Add Error: {e}")
        await msg.reply_text("❌ خطای غیرمنتظره. دوباره تلاش کنید.")
        return GET_CHANNEL_FORWARD


async def set_channel_type_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    usage = query.data.split('_')[1]
    cdata = context.user_data['new_chan']
    db.add_channel(update.effective_user.id, cdata['id'], cdata['name'], usage)
    await query.message.reply_text(f"✅ کانال {cdata['name']} ثبت شد.")
    await channels_menu(update, context)
    return ConversationHandler.END


async def delete_channel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.delete_channel(int(update.callback_query.data.split('_')[1]), update.effective_user.id)
    await channels_menu(update, context)


async def edit_expiry_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass
    sid = query.data.split('_')[2]
    context.user_data['edit_expiry_sid'] = sid
    srv = db.get_server_by_id(sid)
    txt = (
        f"📅 **تغییر زمان انقضای سرور: {srv['name']}**\n\n"
        f"🔢 لطفاً **تعداد روزهای باقی‌مانده** را به عدد وارد کنید.\n"
        f"مثلاً اگر عدد `30` را بفرستید، انقضا روی ۳۰ روز دیگر تنظیم می‌شود.\n\n"
        f"♾ برای **نامحدود** کردن، عدد `0` را بفرستید."
    )
    await safe_edit_message(update, txt, reply_markup=keyboard.get_cancel_markup())
    return EDIT_SERVER_EXPIRY


async def edit_expiry_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        sid = context.user_data.get('edit_expiry_sid')
        if days > 0:
            new_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            msg = f"✅ تاریخ انقضا با موفقیت روی **{days} روز دیگر** تنظیم شد."
        else:
            new_date = None
            msg = "✅ سرور با موفقیت **نامحدود (Lifetime)** شد."
        db.update_server_expiry(sid, new_date)
        await update.message.reply_text(msg)
        await server_detail(update, context, custom_sid=sid)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید.")
        return EDIT_SERVER_EXPIRY


async def ask_terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    sid = query.data.split('_')[2]
    srv = db.get_server_by_id(sid)
    context.user_data['term_sid'] = sid

    kb = [[InlineKeyboardButton("🔙 خروج و بازگشت به پنل", callback_data='exit_terminal')]]

    txt = (
        f"📟 **ترمینال تعاملی: {srv['name']}**\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🟢 **اتصال برقرار شد.**\n"
        f"هر دستوری بنویسی اجرا میشه. برای خروج دکمه پایین رو بزن.\n\n"
        f"root@{srv['ip']}:~# _"
    )

    await query.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return GET_REMOTE_COMMAND


async def run_terminal_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = update.message.text
    if cmd.lower() in ['exit', 'quit']:
        return await close_terminal_session(update, context)

    sid = context.user_data.get('term_sid')
    srv = db.get_server_by_id(sid)

    wait_msg = await update.message.reply_text(f"⚙️ `{cmd}` ...")

    real_pass = sec.decrypt(srv['password'])
    ok, output = await ServerMonitor.run_remote_command(srv['ip'], srv['port'], srv['username'], real_pass, cmd)

    if not output: output = "[No Output]"
    if len(output) > 3000: output = output[:3000] + "\n..."
    safe_output = html.escape(output)
    status = "✅" if ok else "❌"

    terminal_view = (
        f"<code>root@{srv['ip']}:~# {cmd}</code>\n"
        f"{status}\n"
        f"<pre language='bash'>{safe_output}</pre>"
    )

    kb = [[InlineKeyboardButton("🔙 خروج از ترمینال", callback_data='exit_terminal')]]
    await wait_msg.delete()
    try:
        await update.message.reply_text(terminal_view, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
    except:
        await update.message.reply_text(f"⚠️ Raw Output:\n{output}", reply_markup=InlineKeyboardMarkup(kb))

    return GET_REMOTE_COMMAND


async def close_terminal_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass
    sid = context.user_data.get('term_sid')
    await server_detail(update, context, custom_sid=sid)
    return ConversationHandler.END
# ==============================================================================async def get_custom_ws_port(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive a custom WS port from user during server add flow."""
    try:
        text = (update.message.text or "").strip()
        if not text.isdigit():
            await update.message.reply_text("❌ لطفاً فقط عدد پورت را ارسال کنید (مثلاً 8081).")
            return GET_CUSTOM_WS_PORT

        port = int(text)
        if port < 1 or port > 65535:
            await update.message.reply_text("❌ پورت نامعتبر است. عددی بین 1 تا 65535 ارسال کنید.")
            return GET_CUSTOM_WS_PORT

        context.user_data['srv']['ws_port'] = port
        await update.message.reply_text("📅 حالا تاریخ انقضا را وارد کنید (مثلاً 2026-01-01):")
        return GET_EXPIRY
    except Exception as e:
        logger.error("get_custom_ws_port failed: %s", e, exc_info=True)
        await update.message.reply_text("❌ خطا در دریافت پورت. دوباره تلاش کنید.")
        return GET_CUSTOM_WS_PORT



