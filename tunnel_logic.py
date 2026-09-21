"""
tunnel_logic.py — نسخه ۴.۲

تغییرات نسبت به ۴.۱ (همه مربوط به رفع «قفل شدن ربات برای بقیه کاربرها»):

1) تست کانفیگ از روی WebSocket انجام می‌شود، نه SSH.
   در ۴.۱ تابع `_exec_via_ws` اسمش وب‌سوکت بود ولی در عمل SSH می‌زد و به ازای
   هر کانفیگ یک `python3 monitor_agent.py` جدید روی سرور ایران بالا می‌آورد.

2) صف عادلانه (fair queue):
   قبلاً یک `Semaphore(5)` سراسری بین همه‌ی کاربرها مشترک بود؛ اگر کاربر A یک
   ساب ۲۰۰ تایی تست می‌کرد، کاربر B باید تا آخرش صبر می‌کرد.
   حالا: سقف سراسری + سقف جداگانه برای هر کاربر.

3) دیتابیس دیگر روی event loop اجرا نمی‌شود.
   قبلاً `process_sub_async` به ازای هر خط خروجی یک INSERT جداگانه می‌زد،
   آن هم مستقیم روی لوپ. برای یک ساب ۳۰۰ تایی یعنی ۳۰۰ بار قفل شدن کل ربات.
   حالا: پارس کامل → یک batch insert → داخل ترد جداگانه.
"""

import logging
import json
import asyncio
import html
import re
from datetime import datetime

from psycopg2.extras import execute_values

# --- Telegram Imports ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# --- Local Modules ---
import keyboard
from database import Database
from core import extract_safe_json, sec, ServerMonitor
from runtime import run_sync
from settings import AGENT_PORT

logger = logging.getLogger(__name__)


# ==============================================================================
# ⚙️ سقف‌های همزمانی
# ==============================================================================
# سقف کل تست‌های همزمانِ در حال اجرا روی نود مانیتورینگ
GLOBAL_TEST_LIMIT = 20
# سقف تست همزمان برای هر کاربر (تا یک نفر کل صف را نبلعد)
PER_USER_TEST_LIMIT = 3


class TunnelLogic:
    def __init__(self):
        self.db = Database()
        self.global_sem = asyncio.Semaphore(GLOBAL_TEST_LIMIT)
        self._user_sems: dict = {}

    # ------------------------------------------------------------------
    def _user_sem(self, uid) -> asyncio.Semaphore:
        """سمافور اختصاصی هر کاربر (صف عادلانه)."""
        key = int(uid or 0)
        sem = self._user_sems.get(key)
        if sem is None:
            sem = asyncio.Semaphore(PER_USER_TEST_LIMIT)
            self._user_sems[key] = sem
        return sem

    def decrypt(self, txt: str) -> str:
        return sec.decrypt(txt)

    # ==================================================================
    # 🔌 AGENT HELPERS
    # ==================================================================
    def _agent_creds(self, monitor: dict):
        """(ip, ws_port, token) نود مانیتورینگ."""
        ip = monitor.get('ip')
        ws_port = monitor.get('ws_port') or AGENT_PORT
        token = self.decrypt(monitor.get('password', ''))
        return ip, int(ws_port), token

    async def _test_via_ws(self, monitor: dict, link: str, size: float = 5.0, timeout: int = 60):
        """تست یک کانفیگ روی کانکشن وب‌سوکت پایدار ایجنت."""
        ip, ws_port, token = self._agent_creds(monitor)
        return await ServerMonitor.ws_test_config(ip, ws_port, token, link, size=size, timeout=timeout)

    async def _fetch_sub_links(self, monitor: dict, sub_link: str, timeout: int = 60):
        """دریافت لیست کانفیگ‌های داخل یک لینک اشتراک از طریق ایجنت."""
        ip, ws_port, token = self._agent_creds(monitor)
        res = await ServerMonitor.ws_send_command(
            ip, ws_port, token,
            {"action": "fetch_sub", "link": sub_link},
            timeout=timeout,
        )

        if isinstance(res, dict) and not res.get("error"):
            links = res.get("links") or []
            if links:
                return True, links, res.get("sub_info")

        # فال‌بک: اگر ایجنت قدیمی بود و fetch_sub نداشت، از حالت CLI استفاده کن
        return await self._fetch_sub_links_cli(monitor, sub_link, timeout=timeout)

    async def _fetch_sub_links_cli(self, monitor: dict, sub_link: str, timeout: int = 120):
        """فال‌بک سازگاری با ایجنت‌های قدیمی (اجرای CLI روی نود، از طریق ایجنت)."""
        import shlex

        ip, ws_port, token = self._agent_creds(monitor)
        cmd = f"python3 -u /root/monitor_agent.py {shlex.quote(sub_link)} 0.5"
        res = await ServerMonitor.ws_send_command(
            ip, ws_port, token,
            {"action": "run_cmd", "cmd": cmd, "timeout": timeout},
            timeout=timeout + 10,
        )

        if not isinstance(res, dict) or res.get("error") or not res.get("ok"):
            err = (res or {}).get("error") or (res or {}).get("output") or "agent unreachable"
            return False, err, None

        links, sub_info = [], None
        for line in str(res.get("output", "")).split('\n'):
            m = re.search(r'(\{.*\})', line.strip())
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            if data.get('type') == 'meta' and 'sub_info' in data:
                sub_info = data['sub_info']
            elif data.get('type') == 'sub':
                # خروجی حالت سریع: {"type":"sub","configs":[...]}
                for c in data.get('configs') or []:
                    if c.get('link'):
                        links.append({"name": c.get('name', 'Unknown'), "link": c['link']})
            elif data.get('type') == 'result' and data.get('link'):
                links.append({"name": data.get('name', 'Unknown'), "link": data['link']})

        return True, links, sub_info

    # ==================================================================
    # 💾 DATABASE (همه خارج از event loop)
    # ==================================================================
    def _bulk_save_sub_items(self, uid, sub_name, rows):
        """یک‌جا نوشتن نتایج یک اشتراک — به جای یک INSERT به ازای هر کانفیگ."""
        if not rows:
            return
        with self.db.get_connection() as (conn, cur):
            execute_values(
                cur,
                """INSERT INTO tunnel_configs
                   (owner_id, type, link, name, added_at, quality_score,
                    last_status, last_ping, last_jitter, last_speed_down, last_speed_up)
                   VALUES %s
                   ON CONFLICT(link) DO UPDATE SET
                     last_status=EXCLUDED.last_status,
                     last_ping=EXCLUDED.last_ping,
                     last_jitter=EXCLUDED.last_jitter,
                     last_speed_down=EXCLUDED.last_speed_down,
                     last_speed_up=EXCLUDED.last_speed_up,
                     quality_score=EXCLUDED.quality_score""",
                rows,
            )
            conn.commit()

    def _clear_sub_items(self, uid, sub_name):
        with self.db.get_connection() as (conn, cur):
            cur.execute(
                "DELETE FROM tunnel_configs WHERE owner_id=%s AND name LIKE %s AND type='sub_item'",
                (uid, f"{sub_name} | %"),
            )
            conn.commit()

    def _save_sub_info(self, sub_id, sub_info):
        with self.db.get_connection() as (conn, cur):
            cur.execute("UPDATE tunnel_configs SET sub_info=%s WHERE id=%s",
                        (json.dumps(sub_info), sub_id))
            conn.commit()

    def _bulk_update_singles(self, ok_rows, fail_ids):
        with self.db.get_connection() as (conn, cur):
            for r in ok_rows:
                cur.execute(
                    """UPDATE tunnel_configs SET last_status='OK', last_ping=%s, last_jitter=%s,
                       last_speed_down=%s, last_speed_up=%s, quality_score=%s WHERE id=%s""",
                    r,
                )
            if fail_ids:
                cur.execute(
                    "UPDATE tunnel_configs SET last_status='Fail' WHERE id = ANY(%s)",
                    (list(fail_ids),),
                )
            conn.commit()

    def _get_active_monitor(self):
        with self.db.get_connection() as (conn, cur):
            cur.execute("SELECT * FROM servers WHERE is_monitor_node=1 AND is_active=1")
            return cur.fetchone()

    def _register_sub_source(self, uid, sub_link, sub_name):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self.db.get_connection() as (conn, cur):
            cur.execute(
                """INSERT INTO tunnel_configs (owner_id, type, link, name, added_at, quality_score)
                   VALUES (%s, 'sub_source', %s, %s, %s, 10) ON CONFLICT(link) DO NOTHING""",
                (uid, sub_link, sub_name, now),
            )
            cur.execute("SELECT id FROM tunnel_configs WHERE link=%s AND type='sub_source'", (sub_link,))
            row = cur.fetchone()
            conn.commit()
            return row['id'] if row else None

    # ==================================================================
    # 🔄 PROCESSING
    # ==================================================================
    async def process_sub_async(self, uid, sub, monitor: dict):
        """پردازش یک اشتراک: دریافت لینک‌ها، تست موازی، ذخیره یک‌جا."""
        sub_name = sub['name']
        sub_link = sub['link']
        sub_id = sub['id']

        await run_sync(self._clear_sub_items, uid, sub_name)

        ok, links, sub_info = await self._fetch_sub_links(monitor, sub_link)
        if not ok:
            return [f"❌ خطا در اتصال به نود مانیتورینگ: {links}"]

        if sub_info:
            try:
                await run_sync(self._save_sub_info, sub_id, sub_info)
            except Exception as e:
                logger.warning("save sub_info failed: %s", e)

        # تست موازی با رعایت صف عادلانه
        async def _one(item):
            async with self.global_sem, self._user_sem(uid):
                ok_t, data = await self._test_via_ws(monitor, item['link'], size=0.5, timeout=45)
                return item, (data if ok_t else None)

        results = await asyncio.gather(*[_one(i) for i in links], return_exceptions=True)

        now_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        rows, report_lines = [], []

        for res in results:
            if isinstance(res, Exception) or not res:
                continue
            item, data = res
            if not isinstance(data, dict):
                continue

            status = data.get('status', 'Fail')
            c_name = data.get('extracted_name') or item.get('name') or 'Unknown'
            full_name = f"{sub_name} | {c_name}"
            score = data.get('score', 0) if status == 'OK' else 0

            rows.append((
                uid, 'sub_item', item['link'], full_name, now_dt, score, status,
                data.get('ping', 0), data.get('jitter', 0),
                data.get('down', 0), data.get('up', 0),
            ))

            if status == 'OK':
                report_lines.append(
                    f"<b>{html.escape(c_name)}</b>\n"
                    f"├ 📶 Ping: <code>{data.get('ping', 0)}</code>\n"
                    f"└ ⭐️ Score: <code>{score}/10</code>"
                )

        # 🚀 یک نوشتن، داخل ترد — نه ۳۰۰ نوشتن روی event loop
        await run_sync(self._bulk_save_sub_items, uid, sub_name, rows)

        return report_lines

    async def process_singles_async(self, singles, monitor: dict, uid=None):
        """پردازش لیست کانفیگ‌های تکی (موازی + ذخیره دسته‌ای)."""
        async def _one(cfg):
            async with self.global_sem, self._user_sem(uid or cfg.get('owner_id')):
                ok, data = await self._test_via_ws(monitor, cfg['link'], size=0.5, timeout=45)
                return cfg, (data if ok else None)

        results = await asyncio.gather(*[_one(c) for c in singles], return_exceptions=True)

        ok_rows, fail_ids, report_lines = [], [], []
        for res in results:
            if isinstance(res, Exception) or not res:
                continue
            cfg, data = res
            if isinstance(data, dict) and data.get('status') == 'OK':
                score = data.get('score', 0)
                ok_rows.append((
                    data.get('ping', 0), data.get('jitter', 0),
                    data.get('down', 0), data.get('up', 0), score, cfg['id'],
                ))
                bar = "🟩" * int(score) + "⬜️" * (10 - int(score))
                report_lines.append(
                    f"<b>{html.escape(cfg['name'])}</b>\n📶 {data.get('ping', 0)}ms | {bar}"
                )
            else:
                fail_ids.append(cfg['id'])

        await run_sync(self._bulk_update_singles, ok_rows, fail_ids)
        return report_lines

    # ==================================================================
    # 🚀 MAIN ORCHESTRATOR
    # ==================================================================
    async def run_mass_update_process(self, context, uid, subs, singles, monitor, status_msg):
        final_report_groups = []
        tasks = [self.process_sub_async(uid, sub, monitor) for sub in subs]
        if singles:
            tasks.append(self.process_singles_async(singles, monitor, uid=uid))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        idx = 0
        for sub in subs:
            sub_res = results[idx]
            if isinstance(sub_res, Exception):
                logger.error("sub task failed: %s", sub_res)
            elif sub_res:
                final_report_groups.append({
                    "title": f"📂 <b>{html.escape(sub['name'])}</b>",
                    "lines": sub_res,
                })
            idx += 1

        if singles:
            singles_res = results[idx]
            if isinstance(singles_res, Exception):
                logger.error("singles task failed: %s", singles_res)
            elif singles_res:
                final_report_groups.append({
                    "title": "👤 <b>کانفیگ‌های تکی</b>",
                    "lines": singles_res,
                })

        try:
            await status_msg.delete()
        except Exception:
            pass

        if not final_report_groups:
            await context.bot.send_message(
                chat_id=uid,
                text="❌ هیچ کانفیگ سالمی یافت نشد (یا خطا در اتصال به نود مانیتورینگ).",
            )
            return

        header = (
            f"📊 <b>گزارش نهایی تست همگانی</b>\n"
            f"📦 تعداد منابع: {len(final_report_groups)}\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
        )
        await context.bot.send_message(chat_id=uid, text=header, parse_mode='HTML')

        for group in final_report_groups:
            chunk = f"{group['title']}\n➖➖➖➖➖➖➖➖\n"
            for line in group['lines']:
                if len(chunk) + len(line) > 4000:
                    await context.bot.send_message(chat_id=uid, text=chunk, parse_mode='HTML')
                    chunk = ""
                chunk += line + "\n"
            if chunk:
                await context.bot.send_message(chat_id=uid, text=chunk, parse_mode='HTML')

        kb = [[InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='tunnel_list_menu')]]
        await context.bot.send_message(
            chat_id=uid, text="✅ **پایان عملیات.**",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown',
        )

    async def finalize_sub_adding(self, update: Update, context: ContextTypes.DEFAULT_TYPE, temp_sub_link):
        sub_name = update.message.text.strip()
        uid = update.effective_user.id

        status_msg = await update.message.reply_text(
            "⏳ <b>در حال دریافت کانفیگ‌ها...</b>\n(لطفاً صبر کنید)", parse_mode='HTML'
        )

        monitor = await run_sync(self._get_active_monitor)
        if not monitor:
            await status_msg.edit_text(
                "❌ سرور مانیتورینگ فعال نیست (لطفا یک سرور را به عنوان نود مانیتورینگ تنظیم کنید)."
            )
            return ConversationHandler.END

        sub_id = await run_sync(self._register_sub_source, uid, temp_sub_link, sub_name)
        if not sub_id:
            await status_msg.edit_text("❌ ثبت اشتراک در دیتابیس ناموفق بود.")
            return ConversationHandler.END

        report_lines = await self.process_sub_async(
            uid, {'name': sub_name, 'link': temp_sub_link, 'id': sub_id}, monitor
        )

        if report_lines and not report_lines[0].startswith("❌"):
            await status_msg.edit_text(
                f"🏁 <b>عملیات پایان یافت.</b>\n📂 {html.escape(sub_name)}\n"
                f"✅ تعداد سالم: {len(report_lines)}",
                parse_mode='HTML',
            )
        else:
            err = report_lines[0] if report_lines else "خطای ناشناخته"
            await status_msg.edit_text(f"❌ خطا: {err}")

        return ConversationHandler.END


tunnel_manager = TunnelLogic()
