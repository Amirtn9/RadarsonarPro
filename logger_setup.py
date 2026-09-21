import logging
from logging.handlers import RotatingFileHandler
import sys
import traceback
import threading

# تنظیمات اصلی
LOG_FILE_NAME = "sonar_bot.log"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 Megabytes
BACKUP_COUNT = 5  # نگه داشتن 5 فایل قدیمی

def handle_exception(exc_type, exc_value, exc_traceback):
    """این تابع هر خطای مهلکی که باعث کرش برنامه شود را می‌گیرد"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("🔥 Uncaught exception (CRASH):", exc_info=(exc_type, exc_value, exc_traceback))

def handle_thread_exception(args):
    """این تابع خطاهای داخل Thread ها را می‌گیرد"""
    logging.critical("🧵 Uncaught exception in thread:", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

def setup_logger():
    """تنظیمات پیشرفته لاگینگ (Idempotent)

    نکته: پروژه علاوه بر این فایل، از logging_config.py نیز استفاده می‌کند.
    اگر سیستم لاگینگ پیشرفته فعال باشد، این تابع هندلرها را پاک نمی‌کند.
    """

    root_logger = logging.getLogger()

    # اگر سیستم لاگینگ پیشرفته سونار قبلاً تنظیم شده، فقط هوک‌ها/Level ها را اعمال کن
    if getattr(root_logger, '_sonar_logging_configured', False) or root_logger.handlers:
        root_logger.setLevel(logging.DEBUG)
        logging.getLogger('websockets').setLevel(logging.WARNING)
        logging.getLogger('telegram').setLevel(logging.WARNING)
        logging.getLogger('httpx').setLevel(logging.WARNING)
        sys.excepthook = handle_exception
        threading.excepthook = handle_thread_exception
        logging.getLogger(__name__).info('✅ Logging already configured; hooks ensured.')
        return root_logger

    # ───────────────────────────────────────────────────
    # Fallback ساده (اگر logging_config.py فعال نبود)
    # ───────────────────────────────────────────────────

    log_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(funcName)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    file_handler = RotatingFileHandler(
        LOG_FILE_NAME,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.INFO)

    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger('websockets').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception

    logging.getLogger(__name__).info('✅ Advanced Logging System Initialized (fallback).')
    return root_logger