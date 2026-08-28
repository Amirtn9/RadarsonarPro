import logging

# تنظیم لاگر
logger = logging.getLogger(__name__)

class AlertManager:
    """
    مدیریت هشدارها و بررسی آستانه مصرف منابع
    """

    @staticmethod
    def check_resource_thresholds(stats, settings):
        """
        بررسی مصرف منابع نسبت به تنظیمات کاربر
        خروجی: لیستی از پیام‌های هشدار (اگر خالی باشد یعنی همه چیز نرمال است)
        """
        alerts = []
        try:
            # بررسی CPU
            cpu_limit = settings.get('cpu', 80)
            if stats.get('cpu', 0) >= cpu_limit:
                alerts.append(f"🧠 **CPU:** `{stats['cpu']}%` (حد: {cpu_limit}%)")

            # بررسی RAM
            ram_limit = settings.get('ram', 80)
            if stats.get('ram', 0) >= ram_limit:
                alerts.append(f"💾 **RAM:** `{stats['ram']}%` (حد: {ram_limit}%)")

            # بررسی Disk
            disk_limit = settings.get('disk', 90)
            if stats.get('disk', 0) >= disk_limit:
                alerts.append(f"💿 **Disk:** `{stats['disk']}%` (حد: {disk_limit}%)")
                
        except Exception as e:
            logger.error(f"Error checking thresholds: {e}")
            
        return alerts

    @staticmethod
    def get_resource_warning_msg(server_name, alert_list):
        """تولید متن پیام هشدار مصرف منابع"""
        items = "\n".join(alert_list)
        return (
            f"⚠️ **هشدار مصرف منابع**\n"
            f"🖥 سرور: `{server_name}`\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"{items}\n\n"
            f"💡 لطفاً سرور را بررسی کنید."
        )

    @staticmethod
    def get_down_alert_msg(server_name, error, extra_note=""):
        """تولید متن پیام قطع شدن سرور"""
        return (
            f"🚨 **هشدار قطع اتصال (CRITICAL)**\n"
            f"🖥 سرور: `{server_name}`\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"❌ وضعیت: **عدم دسترسی کامل**\n"
            f"🔍 خطا: `{error}`"
            f"{extra_note}"
        )

    @staticmethod
    def get_recovery_msg(server_name):
        """تولید متن پیام وصل شدن مجدد سرور"""
        return (
            f"✅ **اتصال برقرار شد (RECOVERY)**\n"
            f"🖥 سرور: `{server_name}`\n"
            f"♻️ سرور مجدداً در دسترس قرار گرفت."
        )

    @staticmethod
    def get_tunnel_fail_msg(config_name):
        """تولید متن پیام قطعی تانل"""
        return f"🚨 **هشدار:** کانفیگ `{config_name}` قطع شد یا کار نمی‌کند!"