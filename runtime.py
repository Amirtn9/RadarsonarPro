"""
runtime.py — منابع اجرایی مشترک پروژه (نسخه ۴.۲)

چرا این فایل اضافه شد؟
----------------------
در نسخه ۴.۱ پروژه چهار ThreadPoolExecutor جدا داشت:
  - bot_logic_mod/base.py  → 50 ورکر
  - cronjobs.py            → 10 ورکر
  - admin_panel.py         → 10 ورکر
  - و مهم‌تر از همه: استخر «پیش‌فرض» asyncio (run_in_executor(None, ...))
    که اندازه‌اش min(32, cpu_count + 4) است؛ روی یک VPS تک‌هسته‌ای فقط ۵ ترد.

مسیر تست کانفیگ از همین استخر پیش‌فرض استفاده می‌کرد و هر تست تا ۱۲۰ ثانیه
یک ترد را نگه می‌داشت. نتیجه: یک کاربر به‌تنهایی کل استخر را قفل می‌کرد و
بقیه‌ی کاربرها (آمار سرور، نصب ایجنت، دانلود لوگو و ...) پشت صف می‌ماندند.

از نسخه ۴.۲ همه‌ی کارهای سینکرون به یک استخر مشترک و بزرگ می‌روند و
هیچ‌جای پروژه دیگر `run_in_executor(None, ...)` صدا زده نمی‌شود.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

# تعداد ورکرها از env قابل تنظیم است (برای سرورهای کوچک می‌توان کم کرد)
MAX_WORKERS = int(os.getenv("SONAR_EXECUTOR_WORKERS", "48"))

SHARED_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_WORKERS,
    thread_name_prefix="sonar",
)

logger.info("🔧 SHARED_EXECUTOR initialized with %s workers", MAX_WORKERS)

T = TypeVar("T")


async def run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """اجرای یک تابع سینکرون (SSH / psycopg2 / requests) بدون قفل کردن event loop.

    همیشه از این استفاده کنید، نه از run_in_executor(None, ...).
    """
    loop = asyncio.get_running_loop()
    if kwargs:
        from functools import partial

        return await loop.run_in_executor(SHARED_EXECUTOR, partial(func, *args, **kwargs))
    return await loop.run_in_executor(SHARED_EXECUTOR, func, *args)


async def db_call(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """معادل run_sync، فقط برای خوانایی بیشتر در محل کوئری‌های دیتابیس."""
    return await run_sync(func, *args, **kwargs)


def shutdown() -> None:
    try:
        SHARED_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except TypeError:  # python < 3.9
        SHARED_EXECUTOR.shutdown(wait=False)


# ==============================================================================
# 🩺 EVENT LOOP WATCHDOG (نسخه ۴.۳)
# ==============================================================================
# این ابزار تشخیصی است و جواب یک سوال کلیدی را می‌دهد:
#
#   وقتی ربات «هنگ» می‌کند، مشکل از قفل شدن event loop پایتون است،
#   یا از تمام شدن CPU خودِ سرور؟
#
# هر ثانیه یک sleep(1) می‌زنیم و اندازه می‌گیریم واقعاً چقدر طول کشید.
#   - تاخیر بالا + CPU پایین  → کد پایتون لوپ را بلاک کرده
#   - تاخیر بالا + CPU ۱۰۰٪   → کل ماشین اشباع است (ربات و نود ایران یک‌جا؟)
#
# لاگ در /var/log/sonar می‌نشیند:  `⚠️ EVENT LOOP LAG`

_watchdog_task = None


async def _watchdog_loop(threshold: float = 1.0) -> None:
    import time as _time

    while True:
        started = _time.monotonic()
        await asyncio.sleep(1.0)
        lag = _time.monotonic() - started - 1.0

        if lag < threshold:
            continue

        cpu_info = ""
        try:
            import psutil

            cpu_info = (
                f" | cpu={psutil.cpu_percent(interval=None):.0f}%"
                f" load={', '.join(f'{x:.2f}' for x in psutil.getloadavg())}"
                f" ram={psutil.virtual_memory().percent:.0f}%"
            )
        except Exception:
            pass

        logger.warning(
            "⚠️ EVENT LOOP LAG: %.2fs | threads=%s%s",
            lag,
            len([t for t in __import__("threading").enumerate()]),
            cpu_info,
        )


def start_watchdog(threshold: float = 1.0) -> None:
    global _watchdog_task
    if _watchdog_task is not None:
        return
    try:
        _watchdog_task = asyncio.get_running_loop().create_task(_watchdog_loop(threshold))
        logger.info("🩺 Event-loop watchdog started (threshold=%.1fs)", threshold)
    except RuntimeError:
        logger.warning("watchdog not started: no running loop")
