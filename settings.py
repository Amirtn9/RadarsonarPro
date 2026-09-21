import os
import logging
import json

PROJECT_VERSION = "4.3"

# ==============================================================================
# 📂 FILE PATHS CONFIGURATION
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# نام فایل‌های حیاتی
# NOTE: پروژه از PostgreSQL استفاده می‌کند. DB_NAME صرفاً برای سازگاری با بخش‌هایی
# مثل بکاپ‌گیری (خروجی pg_dump) نگه داشته شده است.
DB_NAME = "sonar_ultra_pro.db"
CONFIG_FILE = "sonar_config.json"
KEY_FILE = "secret.key"
AGENT_FILE_PATH = os.path.join(BASE_DIR, "monitor_agent.py")

# ==============================================================================
# ⚙️ DATABASE CONFIGURATION (PostgreSQL)
# ==============================================================================
DB_CONFIG = {
    'dbname': 'sonar_ultra_pro',
    'user': 'sonar_user',
    'password': 'SonarPassword2025',
    'host': 'localhost',
    'port': '5432'
}

# ==============================================================================
# 👤 ADMIN & PORT CONFIGURATION (Dynamic)
# ==============================================================================
SUPER_ADMIN_ID = 0
AGENT_PORT = 8181  # پورت پیش‌فرض

try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            SUPER_ADMIN_ID = int(data.get('admin_id', 0))
            AGENT_PORT = int(data.get('agent_port', 8080)) # خواندن پورت از فایل
except Exception as e:
    print(f"Error loading settings: {e}")

# ==============================================================================
# 💳 SUBSCRIPTION PLANS
# ==============================================================================
SUBSCRIPTION_PLANS = {
    'bronze': {
        'name': 'برنزی 🥉',
        'limit': 5,
        'days': 30,
        'price': 100000,
        'desc': 'مناسب برای استفاده شخصی'
    },
    'silver': {
        'name': 'نقره‌ای 🥈',
        'limit': 10,
        'days': 30,
        'price': 180000,
        'desc': 'مناسب برای تیم‌های کوچک'
    },
    'gold': {
        'name': 'طلایی 🥇',
        'limit': 15,
        'days': 30,
        'price': 240000,
        'desc': 'حرفه‌ای و بدون محدودیت'
    }
}

# ==============================================================================
# 💰 PAYMENT INFO DEFAULT
# ==============================================================================
PAYMENT_INFO = {
    'card': {
        'number': '6037-9979-0000-0000',
        'name': 'نام صاحب حساب'
    },
    'tron': {
        'address': 'TRC20_WALLET_ADDRESS_HERE',
        'network': 'TRC20'
    }
}

# ==============================================================================
# 📟 MONITORING CONFIG
# ==============================================================================
DEFAULT_INTERVAL = 120
DOWN_RETRY_LIMIT = 3

# ============================================================================== 
# 🔌 WEBSOCKET (AGENT) STABILITY SETTINGS
# ============================================================================== 
# این مقادیر به صورت پیش‌فرض، ارتباط وب‌سوکت را "همیشه زنده" نگه می‌دارند.
# در صورت نیاز می‌توانید آن‌ها را در sonar_config.json یا Env تغییر دهید.

# 🔧 نسخه ۴.۲: همه‌ی کاربرها به یک نود مانیتورینگ وصل می‌شوند، یعنی یک
# کلید استخر مشترک. با سقف ۵، نفر ششم ۳۰ ثانیه صبر می‌کرد و خطا می‌گرفت.
WS_POOL_MAX_PER_KEY = int(os.getenv("SONAR_WS_POOL_MAX", "10"))
WS_OPEN_TIMEOUT = float(os.getenv("SONAR_WS_OPEN_TIMEOUT", "6"))
WS_CLOSE_TIMEOUT = float(os.getenv("SONAR_WS_CLOSE_TIMEOUT", "6"))
WS_PING_INTERVAL = float(os.getenv("SONAR_WS_PING_INTERVAL", "30"))
# 🔧 v4.3: زیر بار سنگین ایجنت دیر به ping جواب می‌دهد؛ با ۲۰ ثانیه
# همه‌ی کانکشن‌ها با هم بسته می‌شدند و چرخه‌ی reconnect راه می‌افتاد.
WS_PING_TIMEOUT = float(os.getenv("SONAR_WS_PING_TIMEOUT", "90"))
WS_ACQUIRE_TIMEOUT = float(os.getenv("SONAR_WS_ACQUIRE_TIMEOUT", "45"))

# اگر خروجی ایجنت بزرگ است (مثلاً تست ساب)، max_size=None بهترین گزینه است.
WS_MAX_MESSAGE_SIZE = None

try:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            _data = json.load(f)
            WS_POOL_MAX_PER_KEY = int(_data.get('ws_pool_max', WS_POOL_MAX_PER_KEY))
            WS_PING_INTERVAL = float(_data.get('ws_ping_interval', WS_PING_INTERVAL))
            WS_PING_TIMEOUT = float(_data.get('ws_ping_timeout', WS_PING_TIMEOUT))
except Exception:
    # اگر فایل کانفیگ خراب بود یا نبود، با مقادیر پیش‌فرض ادامه می‌دهیم.
    pass

# ==============================================================================
# 📝 LOGGING CONFIG
# ==============================================================================
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
LOG_LEVEL = logging.INFO