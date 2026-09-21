import logging
import io
import asyncio
import requests
import matplotlib
# تنظیم بک‌اند نمودار برای اجرا در سرور بدون محیط گرافیکی
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# اتصال به هسته اصلی
from core import ServerMonitor
from scoring import ScoreEngine
from settings import AGENT_PORT # دریافت پورت ایجنت

logger = logging.getLogger(__name__)

class StatsManager:
    """
    مدیریت آمار و ارقام سرور (لایه هوشمند)
    """

    @staticmethod
    async def check_full_stats(ip, port, user, password, ws_port=None):
        """
        دریافت آمار به صورت هوشمند (اول وب‌سوکت، اگر نشد SSH)
        """
        # 1. تلاش با وب‌سوکت (روش سریع - اولویت اول) 
        try:
            # استفاده از پورت اختصاصی ایجنت
            ws_res = await ServerMonitor.check_full_stats_ws(ip, AGENT_PORT, password)
            if ws_res.get('status') == 'Online':
                return ws_res
        except Exception as e:
            logger.warning(f"WS Check failed for {ip}: {e}")

        # 2. تلاش با SSH (روش سنتی - فال‌بک)
        # اگر ایجنت نصب نباشد یا پورت بسته باشد، از SSH استفاده می‌کنیم
        try:
            loop = asyncio.get_running_loop()
            # اجرای متد همگام SSH در ترد جداگانه برای جلوگیری از قفل شدن ربات
            ssh_res = await loop.run_in_executor(None, ServerMonitor.check_full_stats, ip, port, user, password)
            return ssh_res
        except Exception as e:
            logger.error(f"SSH Check failed for {ip}: {e}")
            return {'status': 'Offline', 'error': 'Connection Failed', 'cpu': 0, 'ram': 0}

    @staticmethod
    def check_host_api(target):
        """استعلام از Check-Host"""
        return ServerMonitor.check_host_api(target)

    @staticmethod
    def format_check_host_results(data):
        return ServerMonitor.format_check_host_results(data)

    @staticmethod
    def format_full_global_results(data):
        # بررسی وجود تابع در هسته برای جلوگیری از خطا
        if hasattr(ServerMonitor, 'format_full_global_results'):
            return ServerMonitor.format_full_global_results(data)
        return "Global results not available."

    @staticmethod
    def get_datacenter_info(ip):
        """دریافت اطلاعات دیتاسنتر و لوکیشن"""
        try:
            r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,isp,query", timeout=5)
            return True, r.json()
        except Exception as e:
            return False, str(e)

    @staticmethod
    def make_bar(percentage, length=10):
        return ScoreEngine.make_bar(percentage, length)

    @staticmethod
    def generate_plot(server_name, stats):
        """تولید نمودار مصرف منابع"""
        if not stats:
            return None
        try:
            fig = Figure(figsize=(10, 5))
            ax = fig.add_subplot(111)

            times = [s['time_str'] for s in stats]
            cpus = [s['cpu'] for s in stats]
            rams = [s['ram'] for s in stats]

            ax.plot(times, cpus, label='CPU (%)', color='red', linewidth=2)
            ax.plot(times, rams, label='RAM (%)', color='blue', linewidth=2)

            ax.set_title(f"Server Monitor: {server_name} (Last 24h)")
            ax.set_xlabel('Time')
            ax.set_ylabel('Usage %')
            ax.set_ylim(0, 100)
            ax.legend()
            ax.grid(True, linestyle='--', alpha=0.6)

            if len(times) > 10:
                step = max(1, len(times) // 8)
                ax.set_xticks(range(0, len(times), step))
                ax.set_xticklabels(times[::step], rotation=45)

            fig.tight_layout()
            buf = io.BytesIO()
            FigureCanvasAgg(fig).print_png(buf)
            buf.seek(0)
            return buf
        except Exception as e:
            logger.error(f"Plot error: {e}")
            return None