import logging
import json
import asyncio
import html
import re
import shlex
from datetime import datetime

# --- Telegram Imports ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# --- Local Modules ---
import keyboard
from database import Database
from core import extract_safe_json, sec, ServerMonitor

logger = logging.getLogger(__name__)

class TunnelLogic:
    def __init__(self):
        self.db = Database()
        # ✅ کنترل همزمانی: حداکثر 5 درخواست همزمان به ایجنت
        # اگر عدد را زیاد کنید ممکن است ایجنت روی سرور ضعیف کرش کند
        self.semaphore = asyncio.Semaphore(5)

    def decrypt(self, txt: str) -> str:
        # استفاده از Security مرکزی پروژه (core.sec)
        return sec.decrypt(txt)

    # ==========================================================================
    # 🔌 WEBSOCKET HELPER (ارتباط پایدار با ایجنت)
    # ==========================================================================
    async def _exec_via_ws(self, monitor: dict, command: str, timeout: int = 60):
        """ارسال دستور به ایجنت از طریق وب‌سوکت (کانکشن پایدار) و دریافت خروجی."""

        ip = monitor.get('ip')
        ssh_port = monitor.get('port', 22)
        username = monitor.get('username', 'root')
        token_pass = self.decrypt(monitor.get('password', ''))

        # ServerMonitor.run_remote_command از WebSocketPool استفاده می‌کند
        ok, output = await ServerMonitor.run_remote_command(
            ip, ssh_port, username, token_pass, command, timeout=timeout
        )
        return ok, output

    # ==========================================================================
    # 🔄 ASYNC PROCESS METHODS
    # ==========================================================================
    
    async def process_sub_async(self, uid, sub, monitor: dict):
        """پردازش اشتراک (ساب) به صورت Async و مدیریت شده"""
        async with self.semaphore:  # رعایت صف
            sub_name = sub['name']
            sub_link = sub['link']
            sub_id = sub['id']
            report_lines = []

            # 1. پاکسازی دیتابیس
            with self.db.get_connection() as (conn, cur):
                cur.execute("DELETE FROM tunnel_configs WHERE owner_id=%s AND name LIKE %s AND type='sub_item'", (uid, f"{sub_name} | %"))
                conn.commit()

            # 2. اجرای دستور روی سرور (استفاده از حالت CLI ایجنت)
            # استفاده از shlex برای امنیت بیشتر در دستورات شل
            safe_link = shlex.quote(sub_link)
            cmd = f"python3 -u /root/monitor_agent.py {safe_link} 5.0"
            
            ok, output = await self._exec_via_ws(monitor, cmd, timeout=120)

            if not ok:
                return [f"❌ خطا در اتصال به سرور: {output}"]

            # 3. پارس کردن خروجی
            for line in output.split('\n'):
                line = line.strip()
                if not line: continue
                
                # پیدا کردن JSON در خط
                json_match = re.search(r'(\{.*\})', line)
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
                        
                        # --- Meta Info ---
                        if data.get('type') == 'meta':
                            if 'sub_info' in data:
                                info_str = json.dumps(data['sub_info'])
                                with self.db.get_connection() as (conn, cur):
                                    cur.execute("UPDATE tunnel_configs SET sub_info=%s WHERE id=%s", (info_str, sub_id))
                                    conn.commit()

                        # --- Result Info ---
                        elif data.get('type') == 'result':
                            c_status = data.get('status')
                            c_name = data.get('name', 'Unknown')
                            c_link = data.get('link')
                            full_name = f"{sub_name} | {c_name}"
                            q_score = data.get('score', 0) if c_status == 'OK' else 0
                            now_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            
                            with self.db.get_connection() as (conn, cur):
                                cur.execute(
                                    """INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score, last_status, last_ping, last_jitter, last_speed_down, last_speed_up) 
                                       VALUES (%s, 'sub_item', %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                                       ON CONFLICT(link) DO UPDATE SET last_status=EXCLUDED.last_status, last_ping=EXCLUDED.last_ping, quality_score=EXCLUDED.quality_score""",
                                    (uid, c_link, full_name, now_dt, q_score, c_status, data.get('ping',0), data.get('jitter',0), data.get('down',0), data.get('up',0))
                                )
                                conn.commit()

                            if c_status == 'OK':
                                line_txt = (f"<b>{html.escape(c_name)}</b>\n├ 📶 Ping: <code>{data.get('ping',0)}</code>\n└ ⭐️ Score: <code>{q_score}/10</code>")
                                report_lines.append(line_txt)
                    
                    except Exception as e:
                        logger.error(f"JSON Parse Error: {e}")

            return report_lines

    async def process_singles_async(self, singles, monitor: dict):
        """پردازش لیست کانفیگ‌های تکی"""
        report_lines = []
        tasks = []
        for s_cfg in singles:
            tasks.append(self._check_single_config(s_cfg, monitor))
            
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res: report_lines.append(res)
            
        return report_lines

    async def _check_single_config(self, s_cfg, monitor: dict):
        """تست یک کانفیگ تکی"""
        async with self.semaphore:
            safe_name = html.escape(s_cfg['name'])
            safe_link = shlex.quote(s_cfg['link'])
            cmd = f"python3 /root/monitor_agent.py {safe_link} 5.0"
            
            ok, output = await self._exec_via_ws(monitor, cmd, timeout=40)
            
            if ok:
                data = extract_safe_json(output)
                if data and data.get('status') == 'OK':
                    q_score = data.get('score', 0)
                    with self.db.get_connection() as (conn, cur):
                        cur.execute("UPDATE tunnel_configs SET last_status='OK', last_ping=%s, last_jitter=%s, last_speed_down=%s, last_speed_up=%s, quality_score=%s WHERE id=%s",
                            (data.get('ping',0), data.get('jitter',0), data.get('down',0), data.get('up',0), q_score, s_cfg['id']))
                        conn.commit()
                    
                    bar_filled = int(q_score)
                    progress_bar = "🟩" * bar_filled + "⬜️" * (10 - bar_filled)
                    return f"<b>{safe_name}</b>\n📶 {data.get('ping',0)}ms | {progress_bar}"
                else:
                    with self.db.get_connection() as (conn, cur):
                        cur.execute("UPDATE tunnel_configs SET last_status='Fail' WHERE id=%s", (s_cfg['id'],))
                        conn.commit()
            return None

    # ==========================================================================
    # 🚀 MAIN ORCHESTRATOR
    # ==========================================================================

    async def run_mass_update_process(self, context, uid, subs, singles, monitor, status_msg):
        """مدیریت کلی آپدیت همگانی (کاملاً Async)"""
        # monitor dict شامل ip/port/username/password است
        
        final_report_groups = []
        tasks = []
        
        # تسک‌های سابسکریپشن
        for sub in subs:
            tasks.append(self.process_sub_async(uid, sub, monitor))
            
        # تسک کانفیگ‌های تکی
        if singles:
            tasks.append(self.process_singles_async(singles, monitor))
            
        # اجرای همه
        results = await asyncio.gather(*tasks)
        
        # تفکیک نتایج
        idx = 0
        for sub in subs:
            sub_res = results[idx]
            if sub_res:
                safe_sub_name = html.escape(sub['name'])
                final_report_groups.append({"title": f"📂 <b>{safe_sub_name}</b>", "lines": sub_res})
            idx += 1
            
        if singles:
            singles_res = results[idx]
            if singles_res:
                final_report_groups.append({"title": f"👤 <b>کانفیگ‌های تکی</b>", "lines": singles_res})

        # نمایش گزارش
        try: await status_msg.delete()
        except: pass

        if not final_report_groups:
            await context.bot.send_message(chat_id=uid, text="❌ هیچ کانفیگ سالمی یافت نشد (یا خطا در اتصال به سرور تست).")
            return

        header = f"📊 <b>گزارش نهایی تست همگانی</b>\n📦 تعداد منابع: {len(final_report_groups)}\n➖➖➖➖➖➖➖➖➖➖\n"
        await context.bot.send_message(chat_id=uid, text=header, parse_mode='HTML')
        
        for group in final_report_groups:
            chunk = f"{group['title']}\n➖➖➖➖➖➖➖➖\n"
            for line in group['lines']:
                if len(chunk) + len(line) > 4000:
                    await context.bot.send_message(chat_id=uid, text=chunk, parse_mode='HTML')
                    chunk = ""
                chunk += line + "\n"
            if chunk: await context.bot.send_message(chat_id=uid, text=chunk, parse_mode='HTML')

        kb = [[InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='tunnel_list_menu')]]
        await context.bot.send_message(chat_id=uid, text="✅ **پایان عملیات.**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    async def finalize_sub_adding(self, update: Update, context: ContextTypes.DEFAULT_TYPE, temp_sub_link):
        """نهایی‌سازی افزودن اشتراک"""
        sub_name = update.message.text.strip()
        uid = update.effective_user.id
        safe_sub_name = html.escape(sub_name)
        
        status_msg = await update.message.reply_text(f"⏳ <b>در حال دریافت کانفیگ‌ها...</b>\n(لطفاً صبر کنید)", parse_mode='HTML')
        
        with self.db.get_connection() as (conn, cur):
            cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
            monitor = cur.fetchone()
        
        if not monitor:
            await status_msg.edit_text("❌ سرور مانیتورینگ فعال نیست (لطفا یک سرور را به عنوان نود مانیتورینگ تنظیم کنید).")
            return ConversationHandler.END
            
        # اطلاعات کامل مانیتور
        
        # ثبت اولیه
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self.db.get_connection() as (conn, cur):
            cur.execute("INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score) VALUES (%s, 'sub_source', %s, %s, %s, 10) ON CONFLICT(link) DO NOTHING", (uid, temp_sub_link, sub_name, now))
            cur.execute("SELECT id FROM tunnel_configs WHERE link=%s AND type='sub_source'", (temp_sub_link,))
            sub_id = cur.fetchone()['id']
            conn.commit()
            
        fake_sub_obj = {'name': sub_name, 'link': temp_sub_link, 'id': sub_id}
        
        # پردازش
        report_lines = await self.process_sub_async(uid, fake_sub_obj, monitor)
        
        if report_lines and not report_lines[0].startswith("❌"):
            count = len(report_lines)
            await status_msg.edit_text(f"🏁 <b>عملیات پایان یافت.</b>\n📂 {safe_sub_name}\n✅ تعداد سالم: {count}", parse_mode='HTML')
        else:
            err = report_lines[0] if report_lines else "خطای ناشناخته"
            await status_msg.edit_text(f"❌ خطا: {err}")
            
        await asyncio.sleep(2)
        return ConversationHandler.END

tunnel_manager = TunnelLogic()