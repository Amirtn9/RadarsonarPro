"""
🎯 ADVANCED UNIFIED LOGGING SYSTEM FOR SONAR RADAR
═══════════════════════════════════════════════════════

Features:
✅ Multi-handler (File + Console + Syslog*)
✅ Color-coded console output
✅ Structured JSON logging (برای تجزیه آسان)
✅ Automatic log rotation (بر اساس سایز)
✅ Thread-safe + Async-friendly
✅ Performance metrics helpers
✅ Centralized configuration

* Syslog فقط اگر /dev/log وجود داشته باشد فعال می‌شود.
"""

from __future__ import annotations

import json
import logging
import logging.config
import logging.handlers
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Optional


# ───────────────────────────────────────────────────────
# 🎨 COLOR CODES
# ───────────────────────────────────────────────────────

class ColorCodes:
    """ANSI رنگ‌ها برای خروجی ترمینال"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Background
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"

    _disabled: bool = False

    @classmethod
    def disable(cls) -> None:
        """
        اگر ترمینال رنگ رو سپورت نکنه:
        فقط ثابت‌های رنگ (UPPERCASE) را خالی می‌کنیم تا خودِ disable خراب نشود.
        """
        if cls._disabled:
            return

        # فقط constantهای UPPERCASE که رشته هستند
        for attr, value in list(cls.__dict__.items()):
            if attr.isupper() and isinstance(value, str):
                setattr(cls, attr, "")

        cls._disabled = True


def _should_disable_colors() -> bool:
    """تشخیص اینکه رنگ باید خاموش شود یا نه"""
    if os.getenv("NO_COLOR"):
        return True
    if os.getenv("TERM") == "dumb":
        return True
    try:
        return not sys.stdout.isatty()
    except Exception:
        return True


# ───────────────────────────────────────────────────────
# 📝 CUSTOM FORMATTERS
# ───────────────────────────────────────────────────────

class ColoredConsoleFormatter(logging.Formatter):
    """فرمت رنگی برای کنسول"""

    LEVEL_COLORS = {
        "DEBUG": ColorCodes.CYAN,
        "INFO": ColorCodes.GREEN,
        "WARNING": ColorCodes.YELLOW,
        "ERROR": ColorCodes.RED,
        "CRITICAL": ColorCodes.BG_RED + ColorCodes.WHITE,
    }

    LEVEL_ICONS = {
        "DEBUG": "🔧",
        "INFO": "ℹ️",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "🔥",
    }

    def format(self, record: logging.LogRecord) -> str:
        # اگر محیط رنگ را پشتیبانی نکند، رنگ‌ها را غیرفعال می‌کنیم
        if _should_disable_colors():
            ColorCodes.disable()

        level_name = record.levelname
        color = self.LEVEL_COLORS.get(level_name, ColorCodes.RESET)
        icon = self.LEVEL_ICONS.get(level_name, "•")

        # Timestamp دقیق از record.created (نه datetime.now)
        dt = datetime.fromtimestamp(record.created)
        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")

        thread_name = threading.current_thread().name[:10]
        location = f"{record.filename}:{record.lineno}"
        func_name = record.funcName or "module"

        log_message = (
            f"{ColorCodes.BOLD}{timestamp}{ColorCodes.RESET} | "
            f"{color}{icon} {level_name:<8}{ColorCodes.RESET} | "
            f"{ColorCodes.MAGENTA}{thread_name:<10}{ColorCodes.RESET} | "
            f"{ColorCodes.BLUE}{location:<30}{ColorCodes.RESET} | "
            f"{ColorCodes.CYAN}{func_name}(){ColorCodes.RESET} | "
            f"{record.getMessage()}"
        )

        if record.exc_info:
            log_message += "\n" + self.formatException(record.exc_info)

        return log_message


class JSONFormatter(logging.Formatter):
    """فرمت JSON برای فایل (تحلیل آسان‌تر)"""

    def format(self, record: logging.LogRecord) -> str:
        # ISO timestamp (UTC) برای تحلیل راحت‌تر در ابزارها
        ts_utc = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        log_data: Dict[str, Any] = {
            "timestamp": ts_utc,
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": threading.current_thread().name,
            "message": record.getMessage(),
            "process_id": record.process,
            "thread_id": record.thread,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # اگر extra data بود
        extra_data = getattr(record, "extra_data", None)
        if isinstance(extra_data, dict):
            # جلوگیری از overwrite شدن کلیدهای حساس
            for k, v in extra_data.items():
                if k not in log_data:
                    log_data[k] = v
                else:
                    log_data[f"extra_{k}"] = v

        return json.dumps(log_data, ensure_ascii=False)


# ───────────────────────────────────────────────────────
# 🎯 MAIN LOGGER SETUP
# ───────────────────────────────────────────────────────

def setup_advanced_logging(
    log_dir: str = "/var/log/sonar",
    level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    max_bytes: int = 50 * 1024 * 1024,  # 50 MB
    backup_count: int = 10,
) -> logging.Logger:
    """تنظیم جامع لاگینگ"""

    root_logger = logging.getLogger()

    # ✅ اگر قبلاً تنظیم شده، دوباره هندلر اضافه نکنیم
    if getattr(root_logger, "_sonar_logging_configured", False):
        return logging.getLogger(__name__)

    # ایجاد دایرکتوری لاگ
    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise PermissionError(
            f"Permission denied for log_dir='{log_dir}'. "
            f"Run as root or set log_dir to a writable path."
        ) from e

    # Syslog only if available
    syslog_available = os.path.exists("/dev/log")

    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "colored": {"()": ColoredConsoleFormatter},
            "json": {"()": JSONFormatter},
            "simple": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"},
        },
        "handlers": {
            # ✅ کنسول (رنگی)
            "console": {
                "class": "logging.StreamHandler",
                "level": console_level,
                "formatter": "colored",
                "stream": "ext://sys.stdout",
            },

            # ✅ فایل اصلی (JSON - تمام لاگ‌ها)
            "file_json": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level,
                "formatter": "json",
                "filename": f"{log_dir}/sonar.json",
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
            },

            # ✅ فایل متنی (خوانا)
            "file_text": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level,
                "formatter": "simple",
                "filename": f"{log_dir}/sonar.log",
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
            },

            # ✅ فایل خطاها (فقط ERROR و CRITICAL)
            "file_errors": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": logging.ERROR,
                "formatter": "json",
                "filename": f"{log_dir}/sonar_errors.json",
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
            },
        },

        # ✅ Root logger (در dictConfig باید کلید 'root' باشد)
        "root": {
            "level": level,
            "handlers": ["console", "file_json", "file_text", "file_errors"],
        },

        "loggers": {
            # Library-specific overrides
            "websockets": {
                "level": logging.WARNING,
                "handlers": ["console", "file_text"],
                "propagate": False,
            },
            "telegram": {
                "level": logging.WARNING,
                "handlers": ["console", "file_text"],
                "propagate": False,
            },
            "paramiko": {
                "level": logging.WARNING,
                "handlers": ["console", "file_text"],
                "propagate": False,
            },
            "psycopg2": {
                "level": logging.WARNING,
                "handlers": ["console", "file_text"],
                "propagate": False,
            },

            # Module-specific detailed logging
            "bot_logic": {
                "level": logging.DEBUG,
                "handlers": ["console", "file_json", "file_text"],
                "propagate": False,
            },
            "core": {
                "level": logging.DEBUG,
                "handlers": ["console", "file_json", "file_text"],
                "propagate": False,
            },
            "ws_client": {
                "level": logging.DEBUG,
                "handlers": ["console", "file_json", "file_text", "file_errors"],
                "propagate": False,
            },
            "database": {
                "level": logging.DEBUG,
                "handlers": ["console", "file_json", "file_text", "file_errors"],
                "propagate": False,
            },
        },
    }

    # Syslog handler (optional)
    if syslog_available:
        config["handlers"]["syslog"] = {
            "class": "logging.handlers.SysLogHandler",
            "level": logging.WARNING,
            "formatter": "simple",
            "address": "/dev/log",
            # ✅ مهم: facility باید "local0" باشد نه "LOG_LOCAL0"
            "facility": "local0",
        }
        config["root"]["handlers"].append("syslog")  # type: ignore[index]

    # اعمال تنظیمات
    logging.config.dictConfig(config)

    # idempotent flag
    try:
        logging.getLogger()._sonar_logging_configured = True  # type: ignore[attr-defined]
    except Exception:
        pass

    # پیام راه‌اندازی (فقط یکبار)
    banner = f"""
{ColorCodes.GREEN}{ColorCodes.BOLD}
═══════════════════════════════════════════════════
✅ SONAR UNIFIED LOGGING INITIALIZED
═══════════════════════════════════════════════════
{ColorCodes.RESET}

📂 Log Directory: {log_dir}
📝 Main Logs:  {log_dir}/sonar.json  |  {log_dir}/sonar.log
❌ Errors Log: {log_dir}/sonar_errors.json
🧾 Syslog:     {"ENABLED" if syslog_available else "DISABLED (no /dev/log)"}

🔧 Console Level: {logging.getLevelName(console_level)}
📊 File Level:    {logging.getLevelName(level)}
"""
    try:
        print(banner)
    except Exception:
        pass

    return logging.getLogger(__name__)


# ───────────────────────────────────────────────────────
# 🎁 HELPER FUNCTIONS
# ───────────────────────────────────────────────────────

def log_with_context(logger: logging.Logger, level: str, message: str, **extra: Any) -> None:
    """لاگ کن با اطلاعات اضافی (extra_data)"""
    level_l = (level or "").lower().strip()
    payload = {"extra_data": extra} if extra else None

    if level_l == "debug":
        logger.debug(message, extra=payload)
    elif level_l == "info":
        logger.info(message, extra=payload)
    elif level_l == "warning":
        logger.warning(message, extra=payload)
    elif level_l == "error":
        logger.error(message, extra=payload)
    elif level_l == "critical":
        logger.critical(message, extra=payload)
    else:
        logger.log(logging.INFO, message, extra=payload)


def trace_function(logger: logging.Logger):
    """Decorator برای لاگ کردن ورود/خروج توابع (با حفظ نام تابع)"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug(f"→ ENTER: {func.__name__}() | args={args}, kwargs={kwargs}")
            try:
                result = func(*args, **kwargs)
                logger.debug(f"← EXIT:  {func.__name__}() | result={result}")
                return result
            except Exception as e:
                logger.error(f"✗ EXCEPTION in {func.__name__}(): {e}", exc_info=True)
                raise
        return wrapper
    return decorator


@contextmanager
def time_block(logger: logging.Logger, name: str, level: str = "info", **extra: Any):
    """
    Performance helper:
    با این میتونی زمان اجرای یک بلاک را لاگ کنی.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        log_with_context(
            logger,
            level=level,
            message=f"⏱ {name} took {elapsed_ms:.2f} ms",
            elapsed_ms=round(elapsed_ms, 2),
            **extra,
        )


# ───────────────────────────────────────────────────────
# 🚀 STARTUP
# ───────────────────────────────────────────────────────

if __name__ == "__main__":
    logger = setup_advanced_logging()
    logger.info("🚀 Advanced Logging System Ready!")
    logger.debug("This is a debug message")
    logger.warning("This is a warning message")

    with time_block(logger, "sample_work", level="info", tag="demo"):
        time.sleep(0.15)

    try:
        1 / 0
    except Exception:
        logger.exception("Example exception to verify stacktrace logging")
