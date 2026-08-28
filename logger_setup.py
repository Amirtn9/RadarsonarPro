import logging
from logging.handlers import RotatingFileHandler
import sys

# تنظیمات اصلی
LOG_FILE_NAME = "sonar_bot.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 Megabytes
BACKUP_COUNT = 2  # نگه داشتن 2 فایل قدیمی

def setup_logger():
    """تنظیمات پیشرفته لاگینگ با قابلیت چرخش فایل"""
    
    # فرمت نمایش لاگ
    log_format = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )

    # هندلر فایل (ذخیره در فایل با محدودیت حجم)
    file_handler = RotatingFileHandler(
        LOG_FILE_NAME, 
        maxBytes=MAX_LOG_SIZE, 
        backupCount=BACKUP_COUNT, 
        encoding='utf-8'
    )
    file_handler.setFormatter(log_format)

    # هندلر کنسول (نمایش در ترمینال)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)

    # تنظیمات ریشه (Root Logger)
    logging.basicConfig(
        level=logging.INFO,  # سطح پیش‌فرض (می‌توانید به DEBUG تغییر دهید)
        handlers=[file_handler, console_handler]
    )

    # جلوگیری از لاگ‌های اضافی کتابخانه‌های دیگر (مثل httpcore یا telegram)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)

    return logging.getLogger("SonarLogger")