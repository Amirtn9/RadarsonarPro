import sys
import os
import json
import time
import subprocess
import base64
import urllib.parse
import urllib.request
import zipfile
import re
import random
import socket
import math
import shlex
import argparse
import asyncio
from datetime import datetime, timedelta
import logging

logger = logging.getLogger('ws_client')  # ✅ خودکار به سیستم متصل می‌شه

# ✅ جمع‌آوری لاگ‌های WS (بدون ارجاع به متغیرهای تعریف‌نشده در سطح ماژول)
try:
    logger.debug("WS module initialized (ip=%s, port=%s)", locals().get('ip'), locals().get('port'))
except Exception:
    pass
try:
    logger.debug("WebSocket error hook ready")
except Exception:
    pass
# تلاش برای ایمپورت کتابخانه‌های وب‌سوکت (اگر نصب نباشند، در حالت CLI ارور ندهد)
try:
    import websockets
    import psutil
except ImportError:
    websockets = None
    psutil = None

# ==============================================================================
# ⚙️ SYSTEM CONFIGURATION
# ==============================================================================
USER_HOME = os.path.expanduser("~")
WORK_DIR = os.path.join(USER_HOME, "xray_workspace")
XRAY_BIN = os.path.join(WORK_DIR, "xray")
LOG_FILE = os.path.join(USER_HOME, "agent_debug.log")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TEST_URL = "http://www.google.com/generate_204"

if not os.path.exists(WORK_DIR):
    try: os.makedirs(WORK_DIR, mode=0o755)
    except: pass

def advanced_log(message, category="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{category}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(entry)
    except: pass

# ==============================================================================
# 🛠 UTILITIES (Common)
# ==============================================================================
def get_free_port():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0)); return s.getsockname()[1]
    except: return random.randint(20000, 40000)

def check_port_open(port, timeout=5):
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(('127.0.0.1', port)) == 0: return True
        time.sleep(0.2)
    return False

def decode_base64(data):
    try:
        data = data.strip().replace('\n', '').replace(' ', '')
        missing = len(data) % 4
        if missing: data += '=' * (4 - missing)
        return base64.b64decode(data.replace('-', '+').replace('_', '/')).decode('utf-8', errors='ignore')
    except: return data


# ==============================================================================
# 🔗 SUBSCRIPTION FETCH & PARSE (CLI MODE SUPPORT)
# ==============================================================================
def fetch_url(url, timeout=20):
    """Download subscription content (bytes)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        advanced_log(f"Subscription fetch failed: {e}", "SUB")
        return b""

def normalize_subscription_text(raw_bytes):
    """Return a readable text for v2ray/xray subscriptions (base64 or plain)."""
    try:
        raw_text = raw_bytes.decode("utf-8", errors="ignore").strip()
        if not raw_text:
            return ""
        # Many subs are base64 of multiple lines
        decoded = decode_base64(raw_text)
        if any(proto in decoded for proto in ("vmess://", "vless://", "trojan://", "ss://")):
            return decoded
        return raw_text
    except Exception:
        return ""

def extract_name_from_link(link):
    """Best-effort name extraction from different link formats."""
    try:
        link = (link or "").strip()
        if link.startswith("vmess://"):
            c = json.loads(decode_base64(link[8:]))
            return (c.get("ps") or c.get("remark") or c.get("name") or "").strip()
        # For URL based links, name usually is in fragment (#...)
        p = urllib.parse.urlparse(link)
        if p.fragment:
            return urllib.parse.unquote(p.fragment).replace("+", " ").strip()
        return ""
    except Exception:
        return ""

def parse_subscription_links(text_data, limit=0):
    """Parse subscription text and return list of {'name','link'}."""
    results = []
    if not text_data:
        return results
    lines = [ln.strip() for ln in text_data.replace("\r", "\n").split("\n") if ln.strip()]
    for ln in lines:
        if not (ln.startswith(("vmess://", "vless://", "trojan://", "ss://")) or ln.startswith("{")):
            continue
        name = extract_name_from_link(ln) or f"Item_{len(results)+1}"
        results.append({"name": name, "link": ln})
        if limit and len(results) >= limit:
            break
    return results

# ==============================================================================
# 📦 XRAY MANAGER
# ==============================================================================
def install_xray():
    if os.path.exists(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK): return
    
    advanced_log("Installing Xray...", "INSTALL")
    zip_path = os.path.join(WORK_DIR, "xray.zip")
    urls = [
        "https://mirror.ghproxy.com/https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip",
        "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    ]
    
    for url in urls:
        try:
            subprocess.call(f"curl -L -k -o {zip_path} {url} --connect-timeout 15 --retry 2", shell=True)
            if os.path.exists(zip_path) and os.path.getsize(zip_path) > 1024*1024:
                with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(WORK_DIR)
                os.chmod(XRAY_BIN, 0o755)
                os.remove(zip_path)
                return
        except: pass

# ==============================================================================
# 🧩 PARSING & TESTING LOGIC
# ==============================================================================

def parse_xray_config(link):
    """Parse common v2ray/xray share links into a minimal Xray outbound."""
    try:
        link = (link or "").strip()
        if not link:
            return None

        # JSON outbound (already)
        if link.startswith('{'):
            return json.loads(link)

        # ----------------------------
        # VMESS
        # ----------------------------
        if link.startswith('vmess://'):
            c = json.loads(decode_base64(link[8:]))
            net = c.get('net', 'tcp')
            tls = c.get('tls', 'none')
            stream = {"network": net, "security": tls or "none"}

            if net == 'ws':
                stream["wsSettings"] = {
                    "path": c.get('path', '/') or '/',
                    "headers": {"Host": c.get('host', '') or ""}
                }
            elif net == 'grpc':
                stream["grpcSettings"] = {"serviceName": c.get('path', '') or ""}

            if tls == 'tls':
                stream["tlsSettings"] = {
                    "serverName": (c.get('sni') or c.get('host') or c.get('add') or ""),
                    "allowInsecure": True
                }

            return {
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": c.get('add'),
                        "port": int(c.get('port') or 443),
                        "users": [{
                            "id": c.get('id'),
                            "alterId": 0,
                            "security": c.get('scy', 'auto') or "auto"
                        }]
                    }]
                },
                "streamSettings": stream,
                "tag": "proxy"
            }

        # ----------------------------
        # VLESS
        # ----------------------------
        if link.startswith('vless://'):
            p = urllib.parse.urlparse(link)
            q = urllib.parse.parse_qs(p.query)

            net = q.get('type', ['tcp'])[0]
            sec = q.get('security', ['none'])[0]
            stream = {"network": net, "security": sec or "none"}

            if net == 'ws':
                stream['wsSettings'] = {
                    "path": q.get('path', ['/'])[0] or '/',
                    "headers": {"Host": q.get('host', [''])[0] or ""}
                }
            elif net == 'grpc':
                stream['grpcSettings'] = {"serviceName": q.get('serviceName', [''])[0] or ""}

            if sec == 'tls':
                stream['tlsSettings'] = {
                    "serverName": q.get('sni', [p.hostname or ""])[0] or (p.hostname or ""),
                    "allowInsecure": True
                }
            elif sec == 'reality':
                stream['realitySettings'] = {
                    "publicKey": q.get('pbk', [''])[0] or "",
                    "serverName": q.get('sni', [p.hostname or ""])[0] or (p.hostname or ""),
                    "fingerprint": q.get('fp', ['chrome'])[0] or "chrome"
                }

            return {
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": p.hostname,
                        "port": int(p.port or 443),
                        "users": [{
                            "id": p.username,
                            "encryption": "none",
                            "flow": q.get('flow', [''])[0] or ""
                        }]
                    }]
                },
                "streamSettings": stream,
                "tag": "proxy"
            }

        # ----------------------------
        # TROJAN
        # ----------------------------
        if link.startswith('trojan://'):
            p = urllib.parse.urlparse(link)
            q = urllib.parse.parse_qs(p.query)

            password = p.username or p.password or ""
            net = q.get('type', ['tcp'])[0]
            sec = q.get('security', ['tls'])[0]  # trojan commonly uses tls
            stream = {"network": net, "security": sec or "tls"}

            if net == 'ws':
                stream['wsSettings'] = {
                    "path": q.get('path', ['/'])[0] or '/',
                    "headers": {"Host": q.get('host', [''])[0] or ""}
                }
            elif net == 'grpc':
                stream['grpcSettings'] = {"serviceName": q.get('serviceName', [''])[0] or ""}

            if sec == 'tls':
                stream['tlsSettings'] = {
                    "serverName": q.get('sni', [p.hostname or ""])[0] or (p.hostname or ""),
                    "allowInsecure": True
                }

            return {
                "protocol": "trojan",
                "settings": {
                    "servers": [{
                        "address": p.hostname,
                        "port": int(p.port or 443),
                        "password": password
                    }]
                },
                "streamSettings": stream,
                "tag": "proxy"
            }

        # ----------------------------
        # SHADOWSOCKS (basic)
        # ----------------------------
        if link.startswith('ss://'):
            body = link[5:]
            # strip fragment
            body, _, frag = body.partition('#')
            # strip query
            body, _, _q = body.partition('?')

            method = password = host = None
            port = None

            if '@' in body:
                userinfo, _, hostport = body.rpartition('@')
                if ':' in userinfo:
                    method, password = userinfo.split(':', 1)
                    method = urllib.parse.unquote(method)
                    password = urllib.parse.unquote(password)
                else:
                    dec = decode_base64(userinfo)
                    if ':' in dec:
                        method, password = dec.split(':', 1)
                if ':' in hostport:
                    host, port = hostport.split(':', 1)
            else:
                dec = decode_base64(body)
                if '@' in dec:
                    userinfo, hostport = dec.rsplit('@', 1)
                    if ':' in userinfo:
                        method, password = userinfo.split(':', 1)
                    if ':' in hostport:
                        host, port = hostport.split(':', 1)

            if not (method and password and host and port):
                return None

            return {
                "protocol": "shadowsocks",
                "settings": {
                    "servers": [{
                        "address": host,
                        "port": int(port),
                        "method": method,
                        "password": password
                    }]
                },
                "tag": "proxy"
            }

        return None
    except Exception as e:
        advanced_log(f"parse_xray_config error: {e}", "PARSE")
        return None
def test_config_logic(outbound, dl_size_mb=0.5):
    """لاجیک اصلی تست کانفیگ (Ping + optional Download Speed)."""
    local_port = get_free_port()
    conf_file = os.path.join(WORK_DIR, f"config_{local_port}.json")
    full_conf = {
        "log": {"loglevel": "none"},
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
        "routing": {"domainStrategy": "IPOnDemand", "rules": [{"type": "field", "ip": ["geoip:private", "geoip:ir"], "outboundTag": "direct"}]}
    }

    proc = None
    try:
        with open(conf_file, 'w') as f:
            json.dump(full_conf, f)

        proc = subprocess.Popen([XRAY_BIN, "-c", conf_file], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not check_port_open(local_port):
            return {"status": "Fail", "msg": "Core Start Fail", "ping": 0, "jitter": 0, "down": 0, "up": 0, "score": 0}

        prox = f"socks5://127.0.0.1:{local_port}"
        pings = []

        # Ping Test (3 tries)
        for _ in range(3):
            try:
                cmd = f"curl -x {prox} -s -k -o /dev/null -w '%{{http_code}} %{{time_total}}' {TEST_URL} --max-time 4"
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if "204" in res.stdout:
                    pings.append(float(res.stdout.split()[1]) * 1000)
            except Exception:
                pass

        if not pings:
            return {"status": "Fail", "msg": "Timeout", "ping": 0, "jitter": 0, "down": 0, "up": 0, "score": 0}

        avg_ping = int(sum(pings) / len(pings))
        jitter = int(max(pings) - min(pings)) if len(pings) >= 2 else 0

        # Download Speed Test (Optional)
        dl_spd = 0
        if dl_size_mb and dl_size_mb > 0.5:
            try:
                url = f"https://speed.cloudflare.com/__down?bytes={int(dl_size_mb * 1024 * 1024)}"
                cmd = f"curl -x {prox} -s -k -w '%{{speed_download}}' -o /dev/null {url} --max-time 12"
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                dl_spd = round(float(res.stdout) / 1024 / 1024, 2)
            except Exception:
                dl_spd = 0

        # Simple score
        score = 10
        if avg_ping > 1200:
            score = 1
        elif avg_ping > 800:
            score = 3
        elif avg_ping > 500:
            score = 5
        elif avg_ping > 300:
            score = 7
        elif avg_ping > 150:
            score = 9

        return {"status": "OK", "ping": avg_ping, "jitter": jitter, "down": dl_spd, "up": 0, "score": score}

    except Exception as e:
        return {"status": "Fail", "msg": str(e), "ping": 0, "jitter": 0, "down": 0, "up": 0, "score": 0}

    finally:
        try:
            if proc:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if os.path.exists(conf_file):
                os.remove(conf_file)
        except Exception:
            pass

async def run_sys_command(command, timeout=60):
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output = stdout.decode('utf-8', errors='ignore').strip()
            err_out = stderr.decode('utf-8', errors='ignore').strip()
            final_output = output if output else err_out
            return True, final_output
        except asyncio.TimeoutError:
            try: process.kill()
            except: pass
            return False, "Error: Command Timed Out"
    except Exception as e:
        return False, f"Agent Error: {str(e)}"
"""Sonar Monitor Agent (WebSocket server).

This agent is deployed on remote servers and provides a stable, long-lived
WebSocket interface for:
  - get_stats (CPU/RAM/Disk/Traffic/Uptime)
  - run_cmd (execute system commands with a timeout)
  - test_config (test a single v2ray/xray config link)

Stability improvements in this version:
  - WebSocket keepalive enabled (ping_interval/ping_timeout)
  - Persistent connections supported (multiple requests per connection)
  - Optional token validation (backward compatible)
  - Better JSON error handling
"""

# ==============================================================================
# 🌐 WEBSOCKET SERVER LOGIC
# ==============================================================================

async def get_stats():
    if psutil is None:
        return {"status": "Offline", "error": "psutil not installed"}

    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent
    net = psutil.net_io_counters()

    # Disk usage
    try:
        disk = psutil.disk_usage('/').percent
    except Exception:
        disk = 0

    # محاسبه آپتایم
    uptime_sec = int(time.time() - psutil.boot_time())
    uptime_str = str(timedelta(seconds=uptime_sec))  # ساعت:دقیقه:ثانیه

    return {
        "status": "Online",
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "traffic_gb": round((net.bytes_sent + net.bytes_recv) / (1024**3), 2),
        "uptime_sec": uptime_sec,
        "uptime_str": uptime_str
    }


AGENT_TOKEN = None  # Optional shared secret (string). If None => no auth.

# 🔧 نسخه ۴.۲: کنترل بار روی خود ایجنت.
# حالا که ربات تست‌ها را موازی و روی وب‌سوکت می‌فرستد، ایجنت باید خودش
# سقف داشته باشد؛ وگرنه ده‌ها پروسه xray + curl همزمان بالا می‌آید و
# سرور ایران زانو می‌زند.
AGENT_MAX_PARALLEL_TESTS = int(os.getenv("SONAR_AGENT_MAX_TESTS", "6"))
_TEST_SEMAPHORE = None
_TEST_EXECUTOR = None


def _get_test_semaphore():
    global _TEST_SEMAPHORE
    if _TEST_SEMAPHORE is None:
        _TEST_SEMAPHORE = asyncio.Semaphore(AGENT_MAX_PARALLEL_TESTS)
    return _TEST_SEMAPHORE


def _get_test_executor():
    global _TEST_EXECUTOR
    if _TEST_EXECUTOR is None:
        from concurrent.futures import ThreadPoolExecutor
        _TEST_EXECUTOR = ThreadPoolExecutor(
            max_workers=AGENT_MAX_PARALLEL_TESTS + 4,
            thread_name_prefix="agent-test",
        )
    return _TEST_EXECUTOR


async def ws_handler(websocket, path=None):
    """Handle one connected client.

Protocol:
  1) client sends token (string)
  2) client sends JSON messages forever (request/response)
"""
    try:
        # 1) Receive token (backward compatible: if AGENT_TOKEN is None, accept anything)
        try:
            token = await asyncio.wait_for(websocket.recv(), timeout=12)
        except asyncio.TimeoutError:
            return

        if AGENT_TOKEN is not None and str(token) != str(AGENT_TOKEN):
            try:
                await websocket.close(code=4001, reason="unauthorized")
            except Exception:
                pass
            return

        # 2) Handle requests
        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception:
                try:
                    await websocket.send(json.dumps({"error": "invalid_json"}))
                except Exception:
                    pass
                continue

            action = data.get('action')
            
            if action == 'get_stats':
                await websocket.send(json.dumps(await get_stats()))
                
            elif action == 'test_config':
                # اجرای تست کانفیگ داخل پروسه سرور (بدون باز کردن پایتون جدید)
                # این کار بسیار سریع‌تر از روش SSH است
                link = data.get('link')
                size = data.get('size', 0.5)
                outbound = parse_xray_config(link)
                if outbound:
                    # اجرای تست در ترد جداگانه تا وب‌سوکت قفل نشود
                    # (🔧 v4.2: executor اختصاصی + سقف همزمانی)
                    loop = asyncio.get_running_loop()
                    async with _get_test_semaphore():
                        res = await loop.run_in_executor(
                            _get_test_executor(), test_config_logic, outbound, size
                        )
                    # attach extracted name if possible
                    try:
                        res['extracted_name'] = extract_name_from_link(link) or ''
                    except Exception:
                        pass
                    await websocket.send(json.dumps(res))
                else:
                    await websocket.send(json.dumps({"status": "Fail", "msg": "Parse Error"}))
                    
            elif action == 'fetch_sub':
                # 🆕 نسخه ۴.۲: فقط لیست کانفیگ‌های داخل یک لینک اشتراک را برگردان.
                # تست کردنشان کار سمت ربات است (موازی، با صف عادلانه).
                sub_link = data.get('link')
                loop = asyncio.get_running_loop()

                def _fetch():
                    raw = fetch_url(sub_link, timeout=25)
                    text = normalize_subscription_text(raw)
                    return parse_subscription_links(text)

                try:
                    configs = await loop.run_in_executor(_get_test_executor(), _fetch)
                    await websocket.send(json.dumps({
                        "links": configs,
                        "sub_info": {
                            "url": sub_link,
                            "total": len(configs),
                            "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                            "mode": "list",
                        },
                    }))
                except Exception as e:
                    await websocket.send(json.dumps({"error": f"fetch_sub_failed: {e}"}))

            elif action == 'run_cmd':
                cmd = data.get('cmd')
                # استفاده از تایم‌اوت ارسالی (با سقف ایمن)
                t = data.get('timeout', 120)
                try:
                    t = int(float(t))
                except Exception:
                    t = 120
                if t < 3: t = 3
                if t > 3600: t = 3600
                ok, output = await run_sys_command(cmd, timeout=t)
                await websocket.send(json.dumps({"ok": ok, "output": output}))
            else:
                # Unknown action
                try:
                    await websocket.send(json.dumps({"error": "unknown_action", "action": action}))
                except Exception:
                    pass

    except Exception:
        # Do not crash the server on client errors.
        pass

async def start_server(port):
    if websockets is None:
        raise RuntimeError('websockets not installed. Install with: pip3 install websockets psutil')
    # Keepalive is crucial for long-lived connections behind NAT/firewalls.
    async with websockets.serve(
        ws_handler,
        "0.0.0.0",
        port,
        max_size=None,
        ping_interval=20,
        ping_timeout=20,
    ):
        await asyncio.Future()

# ==============================================================================
# 🏁 MAIN ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    install_xray()

    # CLI args (backward compatible):
    #   python3 monitor_agent.py 8080
    #   python3 monitor_agent.py 8080 --token "..."
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("port", nargs="?", default="8080")
    parser.add_argument("--token", dest="token", default=None)
    args, _ = parser.parse_known_args()

    try:
        if args.token is not None:
            AGENT_TOKEN = str(args.token)
    except Exception:
        pass

    # حالت 1: اجرا به عنوان سرور وب‌سوکت
    # (اگر اولین آرگومان عددی باشد => پورت)
    if str(args.port).isdigit():
        try:
            asyncio.run(start_server(int(args.port)))
        except KeyboardInterrupt:
            pass

    # حالت 2: اجرا به عنوان ابزار تست (CLI Mode - برای سازگاری با کدهای قدیمی)
    elif len(sys.argv) >= 2:
        link = sys.argv[1]
        size = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5

        # اگر لینک سابسکریپشن بود
        if link.startswith(("http://", "https://")):
            raw = fetch_url(link, timeout=25)
            sub_text = normalize_subscription_text(raw)
            configs = parse_subscription_links(sub_text)

            sub_info = {
                "url": link,
                "total": len(configs),
                "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "mode": "tested" if size and size > 0.5 else "list"
            }

            # همیشه یک meta چاپ می‌کنیم تا کدهای جدید/قدیمی سازگار باشند
            print(json.dumps({"type": "meta", "sub_info": sub_info}), flush=True)

            # حالت سریع (فقط لیست)
            if not size or size <= 0.5:
                print(json.dumps({"type": "sub", "configs": configs}), flush=True)
            else:
                # حالت تست کامل (خروجی استریم به صورت result)
                for item in configs:
                    c_link = item.get("link")
                    c_name = item.get("name", "Unknown")
                    outbound = parse_xray_config(c_link)
                    if outbound:
                        res = test_config_logic(outbound, size)
                        res.update({
                            "type": "result",
                            "name": c_name,
                            "link": c_link
                        })
                        if "extracted_name" not in res:
                            res["extracted_name"] = c_name
                        print(json.dumps(res), flush=True)
                    else:
                        print(json.dumps({
                            "type": "result",
                            "name": c_name,
                            "link": c_link,
                            "status": "Fail",
                            "msg": "Parse Error",
                            "ping": 0,
                            "jitter": 0,
                            "down": 0,
                            "up": 0,
                            "score": 0
                        }), flush=True)

        # اگر کانفیگ تکی بود
        else:
            outbound = parse_xray_config(link)
            if outbound:
                res = test_config_logic(outbound, size)
                try:
                    res["extracted_name"] = extract_name_from_link(link) or ""
                except Exception:
                    pass
                print(json.dumps(res), flush=True)
            else:
                print(json.dumps({"status": "Fail", "msg": "Parse Error"}), flush=True)

    # حالت پیش‌فرض: اجرای سرور روی پورت 8080
    else:
        try:
            asyncio.run(start_server(8080))
        except Exception:
            pass

