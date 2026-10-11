import logging
import asyncio
import time
import json
import shlex
import socket
import os
import subprocess
import datetime as dt
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import logging

logger = logging.getLogger('ws_client')  # ✅ خودکار به سیستم متصل می‌شه

# ✅ جمع‌آوری لاگ‌های WS (بدون ارجاع به متغیرهای تعریف‌نشده در سطح ماژول)
try:
    logger.debug("WS module initialized (ip=%s, port=%s)", locals().get('ip'), locals().get('port'))
except Exception:
    pass
try:
    logger.debug("WebSocket error hook ready")
except Exception:
    pass
# --- Local Modules ---
from alerts import AlertManager
from telegram.ext import ContextTypes
from server_stats import StatsManager
import keyboard
from database import Database
from settings import (
    SUPER_ADMIN_ID, DOWN_RETRY_LIMIT, AGENT_FILE_PATH,
    SUBSCRIPTION_PLANS, DB_NAME, KEY_FILE, DB_CONFIG, AGENT_PORT
)
from core import (
    ServerMonitor, get_jalali_str, extract_safe_json, 
    get_tehran_datetime, sec
)
from cryptography.fernet import Fernet

# ==============================================================================
# ⚙️ CONFIGURATION & GLOBALS
# ==============================================================================
logger = logging.getLogger(__name__)
db = Database()

# 🔧 نسخه ۴.۲: استخر مشترک پروژه (قبلاً یک استخر ۱۰ تایی جدا بود)
from runtime import SHARED_EXECUTOR
EXECUTOR = SHARED_EXECUTOR

SERVER_FAILURE_COUNTS = {}
CPU_ALERT_TRACKER = {}
DAILY_REPORT_USAGE = {}
TUNNEL_FAIL_STREAKS = {}
IS_SYSTEM_INITIALIZED = False
LAST_SERVER_REPORT_MIN = {}
LAST_CONFIG_REPORT_MIN = {}

# ==============================================================================
# 🔄 SCHEDULED JOBS
# ==============================================================================

async def global_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی وضعیت کلی سرورها (منابع)"""
    try:
        loop = asyncio.get_running_loop()
        # دریافت لیست سرورهای فعال از دیتابیس
        active_servers = await loop.run_in_executor(EXECUTOR, db.get_active_servers)
        
        if not active_servers:
            return

        for srv in active_servers:
            # اجرای تسک برای هر سرور بدون بلاک کردن بقیه
            asyncio.create_task(check_single_server_resources(context, srv))
            
    except Exception as e:
        logger.error(f"Global Monitor Job Error: {e}")

async def check_single_server_resources(context, srv):
    """بررسی منابع یک سرور خاص"""
    sid = srv['id']
    ip = srv['ip']
    name = srv['name']
    
    try:
        # ✅ پسورد رو رمزگشایی کن (اگر خالی بود، خالی بمون)
        password = srv.get('password', '')
        if password:
            try:
                real_pass = sec. decrypt(password)
            except Exception: 
                real_pass = password  # اگر رمزگشایی شکست خورد، خود رو استفاده کن
        else:
            real_pass = ""
        
        # 1. دریافت آمار (اول وب‌سوکت، بعد SSH)
        stats = await StatsManager.check_full_stats(ip, srv['port'], srv['username'], real_pass, ws_port=srv.get('ws_port'))
        
        # 2. بررسی وضعیت آنلاین/آفلاین
        if stats. get('status') == 'Offline':
            fail_count = SERVER_FAILURE_COUNTS.get(sid, 0) + 1
            SERVER_FAILURE_COUNTS[sid] = fail_count
            
            # اگر از حد مجاز گذشت، هشدار بده
            if fail_count >= DOWN_RETRY_LIMIT:
                if fail_count == DOWN_RETRY_LIMIT:
                    try:
                        from pro_store import ProStore
                        await asyncio.to_thread(ProStore().incident, srv['owner_id'], 'server', sid,
                                                'server_down', f'قطع ارتباط با سرور {name}', 'critical', True)
                    except Exception:logger.exception('Pro incident persistence failed')
                if fail_count == DOWN_RETRY_LIMIT:   # فقط بار اول پیام بده
                    msg = AlertManager.get_down_alert_msg(name, stats. get('error', 'Timeout'))
                    await alert_admin(context, msg)
            return
        else:
            # اگر سرور برگشت، ریست کن
            if SERVER_FAILURE_COUNTS.get(sid, 0) > 0:
                SERVER_FAILURE_COUNTS[sid] = 0
                try:
                    from pro_store import ProStore
                    await asyncio.to_thread(ProStore().incident, srv['owner_id'], 'server',sid,
                                            'server_down', f'بازیابی سرور {name}', 'critical',False)
                except Exception:logger.exception('Pro incident resolution failed')
                # پیام بازگشت (اختیاری)
                # await alert_admin(context, f"✅ سرور {name} آنلاین شد.")

    except Exception as e:
        logger.error(f"Error checking server {name}: {e}")

# Safe, bounded background work; prevent overlapping job runs.
_ACTIVE_JOB_TYPES = set()

async def _settings_snapshot():
    def _query():
        with db.get_connection() as (conn, cur):
            cur.execute("SELECT owner_id,key,value FROM settings")
            return cur.fetchall()
    rows = await asyncio.get_running_loop().run_in_executor(EXECUTOR, _query)
    results = {}
    for row in rows:
        results.setdefault(row['owner_id'], {})[row['key']] = row['value']
    return results


def _datetime_setting(settings, key):
    try:
        return datetime.fromisoformat(settings.get(key, ''))
    except (TypeError, ValueError):
        return datetime.min


async def monitor_tunnels_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic config testing for users with enabled config report intervals."""
    if 'monitor' in _ACTIVE_JOB_TYPES: return
    _ACTIVE_JOB_TYPES.add('monitor')
    try:
        from tunnel_logic import tunnel_manager
        rows = await asyncio.get_running_loop().run_in_executor(EXECUTOR, _scheduled_items_snapshot)
        settings = await _settings_snapshot()
        monitor = await asyncio.get_running_loop().run_in_executor(EXECUTOR, tunnel_manager._get_active_monitor)
        if not monitor: return
        now = datetime.now()
        for uid, configs in rows.items():
            allowed, _ = await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.check_access, uid)
            if not allowed: continue
            st = settings.get(uid, {})
            try: interval = int(st.get('config_report_interval', '0'))
            except ValueError: continue
            if interval <= 0 or (now - _datetime_setting(st, 'last_config_report_at')).total_seconds() < interval * 60:
                continue
            # Save the timestamp *before* starting, preventing duplicate overlapping jobs.
            await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.set_setting, uid, 'last_config_report_at', now.isoformat())
            try:
                result = await tunnel_manager.process_singles_async(configs, monitor, uid=uid)
                await context.bot.send_message(uid,
                    f'📡 گزارش دوره‌ای: {len(result)} کانفیگ سالم از {len(configs)} مورد' +
                    ('\n⚠️ برخی کانفیگ‌ها ناموفق هستند.' if len(result) < len(configs) else ''))
            except Exception:
                logger.exception('Config monitoring failed for %s', uid)
    finally:
        _ACTIVE_JOB_TYPES.discard('monitor')


def _scheduled_items_snapshot():
    with db.get_connection() as (conn, cur):
        cur.execute("SELECT * FROM tunnel_configs WHERE type='single' ORDER BY owner_id,id")
        rows = cur.fetchall()
    by_owner = {}
    for row in rows:
        by_owner.setdefault(row['owner_id'], []).append(row)
    return by_owner


async def _exec_user_servers(uid, action, servers=None):
    if servers is None:
        servers = await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.get_all_user_servers, uid)
    allowed = {
        'update': ('DEBIAN_FRONTEND=noninteractive apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y', 1200),
        'ram': ('sync && echo 3 > /proc/sys/vm/drop_caches', 30),
        'disk': ('apt-get autoremove -y && apt-get clean', 240),
        'full': ('apt-get update -y && apt-get autoremove -y && apt-get clean', 1200),
        'reboot': ('reboot', 30),
    }
    if action not in allowed: raise ValueError('Unsupported global operation')
    cmd, timeout = allowed[action]
    semaphore = asyncio.Semaphore(3)
    async def _one(srv):
        async with semaphore:
            def _owned():
                return db.owns_resource('servers', srv['id'], uid)
            if not await asyncio.get_running_loop().run_in_executor(EXECUTOR, _owned):
                return srv['name'], False, 'ownership denied'
            if not srv.get('is_active'):
                return srv['name'], False, 'inactive'
            try:
                password = sec.decrypt(srv.get('password') or '')
                ok, msg = await ServerMonitor.run_remote_command(srv['ip'], srv['port'], srv['username'], password, cmd, timeout=timeout)
                return srv['name'], ok, msg[-250:]
            except Exception as exc:
                return srv['name'], False, str(exc)[:250]
    return await asyncio.gather(*[_one(srv) for srv in servers])


async def run_global_commands_background(context, uid, servers, action):
    """Implementation of the previously missing bulk-operations handler."""
    try:
        results = await _exec_user_servers(uid, action, servers)
        ok = sum(1 for _, success, _ in results if success)
        detail = '\n'.join(f"{'✅' if good else '❌'} {name}" for name, good, _ in results)
        await context.bot.send_message(uid, f'🌍 نتیجه عملیات {action}: {ok}/{len(results)} موفق\n{detail}'[:4000])
    except Exception:
        logger.exception('Bulk operation failed for %s', uid)
        await context.bot.send_message(uid, '❌ عملیات همگانی ناموفق بود.')


async def auto_scheduler_job(context: ContextTypes.DEFAULT_TYPE):
    """Apply user's configured update and reboot schedules without event-loop blocking."""
    if 'schedule' in _ACTIVE_JOB_TYPES: return
    _ACTIVE_JOB_TYPES.add('schedule')
    try:
        settings = await _settings_snapshot()
        now = get_tehran_datetime().replace(tzinfo=None)
        for uid, st in settings.items():
            allowed, _ = await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.check_access, uid)
            if not allowed: continue
            try:
                interval = int(st.get('auto_update_hours', '0'))
            except ValueError:
                interval = 0
            if interval > 0 and (now - _datetime_setting(st, 'last_auto_update_at')).total_seconds() >= interval*3600:
                await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.set_setting, uid, 'last_auto_update_at', now.isoformat())
                results = await _exec_user_servers(uid, 'update')
                await context.bot.send_message(uid, f'🔄 آپدیت زمان‌بندی‌شده: {sum(ok for _,ok,_ in results)}/{len(results)} سرور')
            reboot = st.get('auto_reboot_config', 'OFF')
            if reboot and reboot != 'OFF':
                try:
                    days_text, hhmm = reboot.split('|')
                    days = int(days_text)
                    scheduled_hour = int(hhmm.split(':')[0])
                    scheduled_minute = int(hhmm.split(':')[1])
                    due = now.replace(hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0)
                    last = _datetime_setting(st, 'last_reboot_at')
                    if days > 0 and 0 <= (now-due).total_seconds() < 180 and (now-last).total_seconds() >= days*86400:
                        await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.set_setting, uid, 'last_reboot_at', now.isoformat())
                        await _exec_user_servers(uid, 'reboot')
                except (ValueError, IndexError):
                    logger.warning('Invalid reboot schedule for %s', uid)
    except Exception:
        logger.exception('Auto scheduler failed')
    finally:
        _ACTIVE_JOB_TYPES.discard('schedule')


async def auto_update_subs_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled subscription refresh; off unless auto_sub_update_hours > 0."""
    if 'subs' in _ACTIVE_JOB_TYPES: return
    _ACTIVE_JOB_TYPES.add('subs')
    try:
        from tunnel_logic import tunnel_manager
        def _load():
            with db.get_connection() as (conn, cur):
                cur.execute("SELECT * FROM tunnel_configs WHERE type='sub_source' ORDER BY owner_id,id")
                return cur.fetchall()
        sources = await asyncio.get_running_loop().run_in_executor(EXECUTOR, _load)
        st_all = await _settings_snapshot()
        monitor = await asyncio.get_running_loop().run_in_executor(EXECUTOR, tunnel_manager._get_active_monitor)
        if not monitor: return
        now = datetime.now()
        for sub in sources:
            uid = sub['owner_id']
            allowed, _ = await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.check_access, uid)
            if not allowed: continue
            st = st_all.get(uid, {})
            try: interval = int(st.get('auto_sub_update_hours', '0'))
            except ValueError: continue
            if interval <= 0 or (now - _datetime_setting(st, f'last_sub_{sub["id"]}')).total_seconds() < interval*3600:
                continue
            await asyncio.get_running_loop().run_in_executor(EXECUTOR, db.set_setting, uid, f'last_sub_{sub["id"]}', now.isoformat())
            try:
                await tunnel_manager.process_sub_async(uid, sub, monitor)
            except Exception:
                logger.exception('Auto sub update failed for %s', sub['id'])
    except Exception:
        logger.exception('Auto subscription job failed')
    finally:
        _ACTIVE_JOB_TYPES.discard('subs')

async def check_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """بررسی سررسید سرویس‌ها"""
    try:
        loop = asyncio.get_running_loop()
        near_expiry = await loop.run_in_executor(EXECUTOR, db.get_near_expiry_services)
        
        if near_expiry:
            msg = "⏳ **لیست سرویس‌های در حال انقضا (۳ روز مانده):**\n\n"
            for s in near_expiry:
                msg += f"🔸 {s['name']} - {s['ip']}\n"
            
            await alert_admin(context, msg)
            
    except Exception as e:
        logger.error(f"Expiry Job Error: {e}")

async def check_bonus_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """Expire bonus capacity exactly once in a locked database transaction."""
    def _expire():
        with db.get_connection() as (conn, cur):
            now = get_tehran_datetime().strftime('%Y-%m-%d %H:%M:%S')
            cur.execute('SELECT id,user_id,bonus_limit FROM temp_bonuses WHERE expires_at <= %s FOR UPDATE', (now,))
            bonuses = cur.fetchall()
            for b in bonuses:
                cur.execute('UPDATE users SET server_limit=GREATEST(0,server_limit-%s) WHERE user_id=%s',
                            (b['bonus_limit'], b['user_id']))
                cur.execute('DELETE FROM temp_bonuses WHERE id=%s', (b['id'],))
            conn.commit()
            return len(bonuses)
    try:
        total = await asyncio.get_running_loop().run_in_executor(EXECUTOR, _expire)
        if total: logger.info('Expired %s bonuses', total)
    except Exception:
        logger.exception('Bonus expiry job failed')

async def auto_backup_send_job(context: ContextTypes.DEFAULT_TYPE):
    """ارسال بکاپ خودکار دیتابیس"""
    if not SUPER_ADMIN_ID: return
    try:
        # ✅ PostgreSQL Backup (pg_dump)
        # DB_NAME اینجا به معنای فایل خروجی بکاپ است.
        now = datetime.now().strftime('%Y%m%d_%H%M%S')
        import tempfile
        fd, backup_path = tempfile.mkstemp(prefix='sonar_auto_backup_', suffix='.dump')
        os.close(fd)

        def _dump():
            env = os.environ.copy()
            env['PGPASSWORD'] = str(DB_CONFIG.get('password', ''))
            cmd = [
                'pg_dump',
                '-h', str(DB_CONFIG.get('host', 'localhost')),
                '-p', str(DB_CONFIG.get('port', '5432')),
                '-U', str(DB_CONFIG.get('user', 'postgres')),
                '-F', 'c',
                '-f', backup_path,
                str(DB_CONFIG.get('dbname', 'postgres')),
            ]
            subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(EXECUTOR, _dump)

        if os.path.exists(backup_path):
            with open(backup_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=SUPER_ADMIN_ID,
                    document=f,
                    caption=f"📦 **Auto Backup (PostgreSQL)**\n📅 {get_jalali_str()}",
                    filename=os.path.basename(backup_path)
                )
        try:
            os.remove(backup_path)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Backup Job Error: {e}")

# ==============================================================================
# 🚀 STARTUP TASKS (LIGHTWEIGHT)
# ==============================================================================

async def startup_whitelist_job(context: ContextTypes.DEFAULT_TYPE):
    """
    ❌ نسخه قبلی: تلاش برای SSH به همه سرورها (باعث کندی می‌شد)
    ✅ نسخه فعلی: غیرفعال شده تا ربات سریع بالا بیاید.
    """
    logger.info("⏩ Startup Whitelist Job skipped for performance.")
    pass 

async def silent_update_monitor_agent():
    """
    ❌ نسخه قبلی: تلاش برای نصب ایجنت روی همه سرورها (باعث گیر کردن می‌شد)
    ✅ نسخه فعلی: غیرفعال. نصب باید دستی یا از منوی ادمین انجام شود.
    """
    logger.info("⏩ Silent Agent Update skipped for performance.")
    pass

async def send_startup_topic_test(context: ContextTypes.DEFAULT_TYPE):
    """تست ارسال پیام در تاپیک‌ها (اختیاری)"""
    pass

async def system_startup_notification(context: ContextTypes.DEFAULT_TYPE):
    """اعلان روشن شدن ربات به ادمین"""
    global IS_SYSTEM_INITIALIZED
    IS_SYSTEM_INITIALIZED = True
    
    if not SUPER_ADMIN_ID: return
    
    try:
        txt = (
            f"🤖 **ربات سونار رادار (Ultra Pro) آنلاین شد!**\n"
            f"📅 زمان: `{get_jalali_str()}`\n"
            f"✅ وضعیت: **Ready**"
        )
        await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Startup Notification Error: {e}")

# ==============================================================================
# 🔔 UTILS
# ==============================================================================

async def alert_admin(context, text):
    """ارسال پیام به ادمین اصلی"""
    if not SUPER_ADMIN_ID: return
    try:
        await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text=text, parse_mode='Markdown')
    except: pass