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
