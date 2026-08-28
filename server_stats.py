import logging
import io
import statistics
import matplotlib
# تنظیم بک‌اند نمودار برای اجرا در سرور بدون محیط گرافیکی
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# اتصال به هسته اصلی (جلوگیری از تکرار کد)
from core import ServerMonitor
from scoring import ScoreEngine

logger = logging.getLogger(__name__)

class StatsManager:
    """
    مدیریت آمار و ارقام سرور (لایه رابط)
    این کلاس حالا فقط وظیفه فرمت‌دهی و رسم نمودار را دارد
    و برای کارهای فنی از Core استفاده می‌کند.
    """

    @staticmethod
    def check_full_stats(ip, port, user, password):
        """دریافت آمار با استفاده از هسته مرکزی"""
        # اتصال و اجرا توسط Core انجام می‌شود
        return ServerMonitor.check_full_stats(ip, port, user, password)

    @staticmethod
    def check_host_api(target):
        """استعلام از Check-Host (از طریق Core)"""
        return ServerMonitor.check_host_api(target)

    @staticmethod
    def format_check_host_results(data):
        """فرمت‌دهی نتایج ایران (از طریق Core)"""
        return ServerMonitor.format_check_host_results(data)

    @staticmethod
    def format_full_global_results(data):
        """فرمت‌دهی نتایج جهانی (از طریق Core)"""
        return ServerMonitor.format_full_global_results(data)

    @staticmethod
    def get_datacenter_info(ip):
        """دریافت اطلاعات دیتاسنتر (از طریق Core)"""
        return ServerMonitor.get_datacenter_info(ip)

    @staticmethod
    def make_bar(percentage, length=10):
        """ساخت نوار وضعیت (از طریق ScoreEngine)"""
        return ScoreEngine.make_bar(percentage, length)

    @staticmethod
    def generate_plot(server_name, stats):
        """
        تولید نمودار گرافیکی مصرف منابع
        (این تابع مختص همین کلاس باقی می‌ماند چون مربوط به نمایش است)
        """
        if not stats:
            return None
        try:
            fig = Figure(figsize=(10, 5))
            ax = fig.add_subplot(111)

            # استخراج داده‌ها از دیتابیس
            times = [s['time_str'] for s in stats]
            cpus = [s['cpu'] for s in stats]
            rams = [s['ram'] for s in stats]

            # رسم خطوط
            ax.plot(times, cpus, label='CPU (%)', color='red', linewidth=2)
            ax.plot(times, rams, label='RAM (%)', color='blue', linewidth=2)

            # تنظیمات ظاهری
            ax.set_title(f"Server Monitor: {server_name} (Last 24h)")
            ax.set_xlabel('Time')
            ax.set_ylabel('Usage %')
            ax.set_ylim(0, 100)
            ax.legend()
            ax.grid(True, linestyle='--', alpha=0.6)

            # مدیریت شلوغی محور افقی (زمان)
            if len(times) > 10:
                step = max(1, len(times) // 8)
                ax.set_xticks(range(0, len(times), step))
                ax.set_xticklabels(times[::step], rotation=45)

            fig.tight_layout()
            
            # خروجی بافر
            buf = io.BytesIO()
            FigureCanvasAgg(fig).print_png(buf)
            buf.seek(0)
            return buf
        except Exception as e:
            logger.error(f"Plot error: {e}")
            return None