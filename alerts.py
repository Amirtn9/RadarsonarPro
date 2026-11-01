"""Alert Management System for Sonar Radar Ultra Pro. 

This module handles: 
- Resource threshold checking (CPU, RAM, Disk)
- Alert message generation
- Server status notifications
- Tunnel/Config failure alerts
"""

import logging
import re

def escape_markdown(text, version=1):
    return re.sub(r'([_*`\[])', r'\\\1', str(text))

# ✅ یکبار import logging (در اول فایل)
# ✅ یکبار تعریف logger (بعد از import)
logger = logging.getLogger(__name__)

logger.debug("📦 alerts.py module loaded")


# ==============================================================================
# 🚨 ALERT MANAGER
# ==============================================================================

class AlertManager:
    """
    مدیریت هشدارها و بررسی آستانه مصرف منابع. 
    
    این کلاس شامل متدهای static برای:
    - بررسی آستانه‌های مصرف منابع
    - تولید پیام‌های هشدار
    - مدیریت وضعیت سرورها
    """

    @staticmethod
    def check_resource_thresholds(stats, settings):
        """
        بررسی مصرف منابع نسبت به تنظیمات کاربر. 
        
        Args:
            stats: دیکشنری شامل آمار منابع (cpu, ram, disk)
            settings: دیکشنری شامل تنظیمات آستانه (cpu_limit, ram_limit, disk_limit)
        
        Returns: 
            لیستی از پیام‌های هشدار (اگر خالی باشد یعنی همه چیز نرمال است)
        """
        alerts = []
        
        try:
            # ✅ بررسی CPU
            cpu_limit = settings. get('cpu', 80)
            cpu_usage = stats.get('cpu', 0)
            
            if cpu_usage >= cpu_limit:
                alerts.append(f"🧠 **CPU:** `{cpu_usage}%` (حد: {cpu_limit}%)")
                logger.warning(f"⚠️ CPU threshold exceeded: {cpu_usage}% >= {cpu_limit}%")

            # ✅ بررسی RAM
            ram_limit = settings.get('ram', 80)
            ram_usage = stats.get('ram', 0)
            
            if ram_usage >= ram_limit:
                alerts.append(f"💾 **RAM:** `{ram_usage}%` (حد: {ram_limit}%)")
                logger.warning(f"⚠️ RAM threshold exceeded:  {ram_usage}% >= {ram_limit}%")

            # ✅ بررسی Disk
            disk_limit = settings.get('disk', 90)
            disk_usage = stats.get('disk', 0)
            
            if disk_usage >= disk_limit:
                alerts.append(f"💿 **Disk:** `{disk_usage}%` (حد: {disk_limit}%)")
                logger.warning(f"⚠️ Disk threshold exceeded: {disk_usage}% >= {disk_limit}%")
            
            if alerts:
                logger.debug(f"📋 Resource alerts generated: {len(alerts)} alert(s)")
            else:
                logger.debug(f"✅ All resources within limits")
                
        except Exception as e:
            logger.error(f"❌ Error checking thresholds:  {e}", exc_info=True)
            
        return alerts

    @staticmethod
    def get_resource_warning_msg(server_name, alert_list):
        """
        تولید متن پیام هشدار مصرف منابع.
        
        Args:
            server_name: نام سرور
            alert_list: لیست پیام‌های هشدار
        
        Returns: 
            متن پیام آماده برای ارسال
        """
        try:
            items = "\n". join(alert_list)
            msg = (
                f"⚠️ **هشدار مصرف منابع**\n"
                f"🖥 سرور:  `{server_name}`\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"{items}\n\n"
                f"💡 لطفاً سرور را بررسی کنید."
            )
            logger.debug(f"📧 Resource warning message generated for {server_name}")
            return msg
        except Exception as e:
            logger.error(f"❌ Error generating resource warning message: {e}", exc_info=True)
            return f"⚠️ خطا در تولید هشدار برای {server_name}"

    @staticmethod
    def get_down_alert_msg(server_name, error, extra_note=""):
        """Telegram Markdown alert for a confirmed host outage."""
        name = escape_markdown(str(server_name), version=1)
        detail = escape_markdown(str(error), version=1)
        note = escape_markdown(str(extra_note), version=1)
        return (
            f"❌ **قطعی سرور**\\n"
            f"🖥 سرور: {name}\\n"
            f"━━━━━━━━━━━━━━━━━━\\n"
            f"وضعیت: **عدم دسترسی**\\n"
            f"جزئیات: {detail}{note}"
        )

    @staticmethod
    def get_recovery_msg(server_name):
        """Telegram Markdown recovery alert."""
        name = escape_markdown(str(server_name), version=1)
        return (
            f"✅ **اتصال سرور بازیابی شد**\\n"
            f"🖥 سرور: {name}\\n"
            f"━━━━━━━━━━━━━━━━━━\\n"
            f"♻️ سرور مجدداً در دسترس است."
        )

    @staticmethod
    def get_agent_down_msg(server_name, error="Agent is not responding"):
        name = escape_markdown(str(server_name), version=1)
        detail = escape_markdown(str(error), version=1)
        return (
            f"❌ **Agent سرور قطع است**\\n"
            f"🖥 سرور: {name}\\n"
            f"━━━━━━━━━━━━━━━━━━\\n"
            f"وضعیت خود سرور: **Online از طریق SSH**\\n"
            f"وضعیت Agent: **Offline**\\n"
            f"جزئیات: {detail}"
        )

    @staticmethod
    def get_agent_recovery_msg(server_name):
        name = escape_markdown(str(server_name), version=1)
        return (
            f"✅ **Agent سرور مجدداً متصل شد**\\n"
            f"🖥 سرور: {name}\\n"
            f"━━━━━━━━━━━━━━━━━━\\n"
            f"دریافت آمار زنده از Agent برقرار شد."
        )

    @staticmethod
    def get_tunnel_fail_msg(config_name):
        """
        تولید متن پیام قطعی تانل/کانفیگ. 
        
        Args:
            config_name: نام کانفیگ/تانل
        
        Returns:
            متن پیام آماده برای ارسال
        """
        try: 
            msg = (
                f"🚨 **هشدار:** کانفیگ `{config_name}` قطع شد یا کار نمی‌کند!\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"⏱ لطفاً به زودی بررسی کنید."
            )
            logger.warning(f"🚨 Tunnel failure for config: {config_name}")
            return msg
        except Exception as e:
            logger.error(f"❌ Error generating tunnel fail message: {e}", exc_info=True)
            return f"🚨 خطا در تولید هشدار برای {config_name}"

    @staticmethod
    def get_tunnel_recovery_msg(config_name):
        """
        تولید متن پیام بازگشت تانل/کانفیگ. 
        
        Args:
            config_name: نام کانفیگ/تانل
        
        Returns:
            متن پیام آماده برای ارسال
        """
        try:
            msg = (
                f"✅ **کانفیگ بازگشت**\n"
                f"🌐 `{config_name}` مجدداً کار می‌کند!"
            )
            logger.info(f"✅ Tunnel recovery for config: {config_name}")
            return msg
        except Exception as e:
            logger.error(f"❌ Error generating tunnel recovery message: {e}", exc_info=True)
            return f"✅ خطا در تولید پیام بازگشت برای {config_name}"


def format_periodic_server_report(servers, timestamp):
    """Build a compact, readable report from the latest stored server samples.

    Each item may contain name/status/cpu/ram/agent_status. Missing metrics are
    shown as unknown rather than fabricated as zero.
    """
    rows = [dict(item) for item in (servers or [])]
    measured = []
    for item in rows:
        try:
            cpu, ram = float(item.get('cpu')), float(item.get('ram'))
            if str(item.get('status') or '').lower() == 'online' and 0 <= cpu <= 100 and 0 <= ram <= 100:
                measured.append((item, (cpu + ram) / 2))
        except (TypeError, ValueError):
            continue
    best = min(measured, key=lambda pair: pair[1]) if measured else None
    lines = [
        "📊 **گزارش دوره‌ای سرورها**",
        f"🕒 {escape_markdown(str(timestamp), version=1)}",
        "",
        f"🖥 تعداد سرورها: **{len(rows)}**",
    ]
    if best:
        lines.append(
            "🏆 کم‌مصرف‌ترین سرور ثبت‌شده: "
            f"**{escape_markdown(str(best[0].get('name') or 'بدون نام'), version=1)}** "
            f"| میانگین CPU/RAM: **{best[1]:.1f}%**"
        )
    lines.extend([
        "ℹ️ رتبه‌بندی براساس آخرین نمونه ثبت‌شده است، نه تست زنده سرعت.",
        "",
    ])
    for item in rows:
        name = escape_markdown(str(item.get('name') or 'بدون نام'), version=1)
        status = str(item.get('status') or 'Unknown').lower()
        icon = '🟢' if status == 'online' else ('❌' if status == 'offline' else '⚪')
        status_text = 'Online' if status == 'online' else ('Offline' if status == 'offline' else 'Unknown')
        agent = str(item.get('agent_status') or 'Unknown').lower()
        agent_text = 'Online' if agent == 'online' else ('Offline' if agent == 'offline' else 'Unknown')
        def metric(key):
            try:
                value = float(item.get(key))
                return f"{value:.1f}%"
            except (TypeError, ValueError):
                return '—'
        lines.append(
            f"{icon} **{name}** | {status_text} | "
            f"CPU {metric('cpu')} | RAM {metric('ram')} | Agent {agent_text}"
        )
    return "\\n".join(lines)


# ==============================================================================
# 📊 ALERT THRESHOLD PROFILES
# ==============================================================================

class AlertThresholds:
    """پروفایل‌های از پیش تعریف‌شده برای آستانه‌های هشدار."""
    
    # پروفایل conservative (محافظه‌کارانه)
    CONSERVATIVE = {
        'cpu': 60,
        'ram': 70,
        'disk': 80,
        'description': '🟢 محافظه‌کارانه (دقیق)'
    }
    
    # پروفایل balanced (متوازن)
    BALANCED = {
        'cpu': 80,
        'ram': 85,
        'disk': 90,
        'description': '🟡 متوازن (پیش‌فرض)'
    }
    
    # پروفایل aggressive (تهاجمی)
    AGGRESSIVE = {
        'cpu': 95,
        'ram': 95,
        'disk': 95,
        'description': '🔴 تهاجمی (متساهل)'
    }
    
    @staticmethod
    def get_profile(name):
        """دریافت پروفایل بر اساس نام."""
        profiles = {
            'conservative': AlertThresholds.CONSERVATIVE,
            'balanced': AlertThresholds.BALANCED,
            'aggressive': AlertThresholds.AGGRESSIVE,
        }
        
        profile = profiles.get(name. lower(), AlertThresholds.BALANCED)
        logger.debug(f"🎯 Alert profile selected: {name} -> {profile['description']}")
        return profile


# ==============================================================================
# 📝 LOGGING HELPERS
# ==============================================================================

def log_alert(level, server_name, alert_type, details):
    """
    لاگ کردن هشدار با فرمت یکنواخت.
    
    Args:
        level: سطح لاگ ('info', 'warning', 'error')
        server_name: نام سرور
        alert_type: نوع هشدار ('resource', 'down', 'recovery', 'tunnel')
        details: جزئیات هشدار
    """
    try:
        msg = f"[{alert_type.upper()}] Server: {server_name} | Details: {details}"
        
        if level == 'info':
            logger.info(msg)
        elif level == 'warning':
            logger.warning(msg)
        elif level == 'error':
            logger.error(msg)
        else:
            logger.debug(msg)
    except Exception as e:
        logger.error(f"❌ Error in log_alert: {e}", exc_info=True)


# ==============================================================================
# 🧪 TESTING & EXAMPLES
# ==============================================================================

if __name__ == "__main__": 
    # تست ساده
    logging.basicConfig(level=logging. DEBUG)
    
    # مثال 1: بررسی آستانه‌ها
    test_stats = {'cpu': 85, 'ram': 75, 'disk': 88}
    test_settings = AlertThresholds. BALANCED
    
    alerts = AlertManager.check_resource_thresholds(test_stats, test_settings)
    print(f"\n📋 Alerts:  {alerts}\n")
    
    if alerts:
        msg = AlertManager.get_resource_warning_msg("Test-Server", alerts)
        print(msg)
    
    # مثال 2: هشدار قطع شدن
    down_msg = AlertManager.get_down_alert_msg("Test-Server", "Connection timeout")
    print(f"\n{down_msg}\n")
    
    # مثال 3: هشدار بازگشت
    recovery_msg = AlertManager.get_recovery_msg("Test-Server")
    print(f"\n{recovery_msg}\n")
    
    # مثال 4: هشدار تانل
    tunnel_msg = AlertManager.get_tunnel_fail_msg("my-config")
    print(f"\n{tunnel_msg}\n")