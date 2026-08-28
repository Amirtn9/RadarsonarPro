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
import logging
import math
import shlex
from datetime import datetime
import argparse
import signal

# ==============================================================================
# ⚙️ SYSTEM CONFIGURATION & LOGGING
# ==============================================================================
USER_HOME = os.path.expanduser("~")
WORK_DIR = os.path.join(USER_HOME, "xray_workspace")
XRAY_BIN = os.path.join(WORK_DIR, "xray")
LOG_FILE = os.path.join(USER_HOME, "agent_debug.log")

TEST_URL = "http://www.google.com/generate_204"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

if not os.path.exists(WORK_DIR):
    try: os.makedirs(WORK_DIR, mode=0o755)
    except: pass

def advanced_log(message, category="INFO"):
    """ثبت لاگ دقیق در فایل برای دیباگ"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{category}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except: pass

# ==============================================================================
# ⏰ ROBUST TIME SYNCHRONIZATION
# ==============================================================================
def sync_system_time():
    """همگام‌سازی زمان از منابع مختلف (جلوگیری از خطای Time Sync در VMess)"""
    sources = [
        "https://www.google.com",
        "https://www.cloudflare.com",
        "https://www.microsoft.com"
    ]
    
    for url in sources:
        try:
            cmd = f"date -s \"$(curl -sI --connect-timeout 3 {url} | grep -i '^date:' | sed 's/^[Dd]ate: //g')\""
            res = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                advanced_log(f"Time synced via {url}", "SYSTEM")
                return
        except: continue
    advanced_log("Time sync failed on all sources.", "WARN")

# ==============================================================================
# 🛠 NETWORK UTILITIES
# ==============================================================================
def get_free_port():
    """یافتن پورت خالی تصادفی"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]
    except: return random.randint(20000, 40000)

def check_port_open(port, timeout=5):
    """بررسی باز شدن پورت محلی"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(('127.0.0.1', port)) == 0: return True
        time.sleep(0.2)
    return False

# ==============================================================================
# 📦 INSTALLATION MANAGER
# ==============================================================================
def install_xray():
    """نصب یا بررسی هسته Xray"""
    if os.path.exists(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK):
        # بررسی سلامت فایل
        try:
            subprocess.check_output([XRAY_BIN, "-version"], stderr=subprocess.STDOUT)
            return
        except:
            advanced_log("Xray binary corrupted, reinstalling...", "WARN")
            os.remove(XRAY_BIN)

    advanced_log("Installing Xray Core...", "INSTALL")
    zip_path = os.path.join(WORK_DIR, "xray.zip")
    
    # لیست میرورها برای عبور از فیلترینگ گیت‌هاب
    urls = [
        "https://mirror.ghproxy.com/https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip",
        "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    ]

    downloaded = False
    for url in urls:
        if downloaded: break
        try:
            advanced_log(f"Downloading from: {url}", "DOWNLOAD")
            # استفاده از curl با retry و timeout
            subprocess.call(f"curl -L -k -o {zip_path} {url} --connect-timeout 15 --max-time 300 --retry 2", shell=True)
            
            if os.path.exists(zip_path) and os.path.getsize(zip_path) > 2 * 1024 * 1024:
                try:
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        if 'xray' in z.namelist(): downloaded = True
                except: pass
        except Exception as e:
            advanced_log(f"Download failed: {e}", "ERROR")

    if not downloaded:
        advanced_log("CRITICAL: Failed to download Xray.", "FATAL")
        sys.exit(1)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(WORK_DIR)
        os.remove(zip_path)
        os.chmod(XRAY_BIN, 0o755)
        advanced_log("Xray installed successfully.", "INSTALL")
    except Exception as e:
        advanced_log(f"Install Error: {e}", "ERROR")
        sys.exit(1)

# ==============================================================================
# 🧩 PARSING LOGIC (HIGH LOGIC)
# ==============================================================================
def decode_base64(data):
    """دیکد هوشمند بیس۶۴ با اصلاح پدینگ"""
    try:
        data = data.strip().replace('\n', '').replace('\r', '').replace(' ', '')
        missing_padding = len(data) % 4
        if missing_padding: data += '=' * (4 - missing_padding)
        data = data.replace('-', '+').replace('_', '/')
        return base64.b64decode(data).decode('utf-8', errors='ignore')
    except: return data

def parse_xray_config(link):
    """تبدیل لینک‌های مختلف به ساختار استاندارد Xray Outbound"""
    try:
        link = link.strip()
        if not link: return None

        # تمیزکاری کوتیشن
        if link.startswith('"') and link.endswith('"'): link = link[1:-1]
        if link.startswith("'") and link.endswith("'"): link = link[1:-1]

        # 1. پردازش JSON مستقیم
        if link.startswith('{'):
            try:
                conf = json.loads(link)
                if 'outbounds' in conf: return conf['outbounds'][0]
                if 'settings' in conf and 'protocol' in conf: return conf 
                return None
            except: return None

        # 2. پردازش VMess
        if link.startswith('vmess://'):
            try:
                b64 = link[8:]
                c = json.loads(decode_base64(b64))
                
                stream = {
                    "network": c.get('net', 'tcp'),
                    "security": c.get('tls', 'none')
                }
                
                # تنظیمات Transport
                if c.get('net') == 'ws':
                    stream["wsSettings"] = {
                        "path": c.get('path', '/'),
                        "headers": {"Host": c.get('host', '')}
                    }
                elif c.get('net') == 'grpc':
                    stream["grpcSettings"] = {"serviceName": c.get('path', '')}
                elif c.get('net') == 'tcp' and c.get('type') == 'http':
                    stream["tcpSettings"] = {
                        "header": {
                            "type": "http",
                            "request": {"headers": {"Host": [c.get('host', '')]}, "path": [c.get('path', '/')]}
                        }
                    }

                # تنظیمات TLS
                if c.get('tls') == 'tls':
                    stream["tlsSettings"] = {
                        "serverName": c.get('sni') or c.get('host'),
                        "allowInsecure": True,
                        "fingerprint": c.get('fp', 'chrome')
                    }

                return {
                    "protocol": "vmess",
                    "settings": {
                        "vnext": [{
                            "address": c.get('add'),
                            "port": int(c.get('port')),
                            "users": [{"id": c.get('id'), "alterId": int(c.get('aid', 0)), "security": "auto"}]
                        }]
                    },
                    "streamSettings": stream,
                    "tag": "proxy"
                }
            except: return None

        # 3. پردازش VLESS / Trojan
        if link.startswith(('vless://', 'trojan://')):
            try:
                parsed = urllib.parse.urlparse(link)
                q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                protocol = 'vless' if link.startswith('vless') else 'trojan'
                
                # استخراج پارامترها با دیکد کردن URL Encoding
                def get_param(key, default=''):
                    val = q.get(key, [default])[0]
                    return urllib.parse.unquote(val)

                stream = {
                    "network": get_param('type', 'tcp'),
                    "security": get_param('security', 'none')
                }

                if stream['network'] == 'ws':
                    stream["wsSettings"] = {"path": get_param('path', '/'), "headers": {"Host": get_param('host')}}
                elif stream['network'] == 'grpc':
                    stream["grpcSettings"] = {"serviceName": get_param('serviceName')}
                elif stream['network'] == 'tcp' and get_param('headerType') == 'http':
                     stream["tcpSettings"] = {
                        "header": {
                            "type": "http",
                            "request": {"headers": {"Host": [get_param('host')]}, "path": [get_param('path', '/')]}
                        }
                    }

                sni = get_param('sni', parsed.hostname)
                if stream['security'] == 'tls':
                     stream["tlsSettings"] = {
                         "serverName": sni, "allowInsecure": True, "fingerprint": get_param('fp', 'chrome')
                     }
                     if get_param('alpn'): stream["tlsSettings"]['alpn'] = get_param('alpn').split(',')
                elif stream['security'] == 'reality':
                     stream["realitySettings"] = {
                         "publicKey": get_param('pbk'), "shortId": get_param('sid'), "serverName": sni, 
                         "fingerprint": get_param('fp', 'chrome'), "spiderX": get_param('spx', '/')
                     }

                return {
                    "protocol": protocol,
                    "settings": {
                        "vnext": [{
                            "address": parsed.hostname,
                            "port": parsed.port,
                            "users": [{
                                "id": parsed.username,
                                "password": parsed.username,
                                "encryption": "none",
                                "flow": get_param('flow')
                            }]
                        }]
                    },
                    "streamSettings": stream,
                    "tag": "proxy"
                }
            except: return None

        # 4. پردازش Shadowsocks (SS)
        if link.startswith('ss://'):
            try:
                body = link[5:]
                if '#' in body: body = body.split('#')[0]
                
                # تشخیص فرمت (SIP002 vs Legacy)
                if '@' in body:
                    # New Format: user:pass@host:port
                    user_info_b64, host_port = body.split('@', 1)
                    host, port = host_port.split(':')
                    user_info = decode_base64(user_info_b64)
                else:
                    # Legacy Format: All Base64
                    decoded = decode_base64(body)
                    if '@' in decoded:
                        user_info, host_port = decoded.split('@', 1)
                        host, port = host_port.split(':')
                    else: return None

                method, password = user_info.split(':', 1)
                
                return {
                    "protocol": "shadowsocks",
                    "settings": {
                        "servers": [{
                            "address": host,
                            "port": int(port),
                            "method": method,
                            "password": password,
                            "ota": False
                        }]
                    },
                    "tag": "proxy"
                }
            except: return None

        return None
    except Exception as e:
        advanced_log(f"Parse Config Error: {e}", "ERROR")
        return None

# ==============================================================================
# 🚀 CORE TESTING LOGIC
# ==============================================================================
def test_config(outbound, dl_size_mb, config_name="Config"):
    """اجرای تست اتصال با Xray Core"""
    advanced_log(f"Testing: {config_name}", "TEST")
    
    local_port = get_free_port()
    config_file = os.path.join(WORK_DIR, f"config_{local_port}.json")
    
    # کانفیگ اجرایی Xray
    full_config = {
        "log": {"loglevel": "error"},
        "inbounds": [{"port": local_port, "listen": "127.0.0.1", "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
        "routing": {
            "domainStrategy": "IPOnDemand",
            "rules": [{"type": "field", "ip": ["geoip:private", "geoip:ir"], "outboundTag": "direct"}]
        }
    }
    
    proc = None
    try:
        with open(config_file, 'w') as f:
            json.dump(full_config, f, indent=2)
            
        proc = subprocess.Popen([XRAY_BIN, "-c", config_file], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        
        # انتظار برای باز شدن پورت
        if not check_port_open(local_port, timeout=2):
            return {"status": "Fail", "msg": "❌ Core Start Fail", "score": 0}
            
        prox = f"socks5://127.0.0.1:{local_port}"
        is_fast_mode = dl_size_mb < 0.3
        total_probes = 2 if is_fast_mode else 5
        conn_timeout = "2" if is_fast_mode else "4"
        
        pings = []
        success_count = 0
        
        # 1. PING TEST
        for _ in range(total_probes):
            try:
                curl_args = [
                    "curl", "-x", prox, "-s", "-k", "-A", USER_AGENT,
                    "-o", "/dev/null", "-w", "%{http_code} %{time_total}",
                    TEST_URL, "--connect-timeout", conn_timeout, "--max-time", "5"
                ]
                res = subprocess.run(curl_args, capture_output=True, text=True)
                parts = res.stdout.split()
                if len(parts) >= 2 and (parts[0] == "204" or parts[0] == "200"):
                    pings.append(float(parts[1]) * 1000)
                    success_count += 1
            except: pass
            time.sleep(0.1 if is_fast_mode else 0.2)
            
        if success_count == 0:
            return {"status": "Fail", "msg": "🚫 Timeout/Filter", "score": 0}

        avg_ping = int(sum(pings) / len(pings))
        jitter = int(math.sqrt(sum([(x - avg_ping) ** 2 for x in pings]) / len(pings))) if len(pings) > 1 else 0

        # 2. SPEED TEST (Optional)
        dl_speed, ul_speed = 0.0, 0.0
        if dl_size_mb > 0.5:
            bytes_dl = int(dl_size_mb * 1024 * 1024)
            url_dl = f"https://speed.cloudflare.com/__down?bytes={bytes_dl}"
            cmd_dl = [
                "curl", "-L", "-k", "-x", prox, "-A", USER_AGENT, "-s",
                "-w", "%{speed_download}", "-o", "/dev/null", url_dl,
                "--connect-timeout", "5", "--max-time", "30"
            ]
            res_dl = subprocess.run(cmd_dl, capture_output=True, text=True)
            try: dl_speed = round(float(res_dl.stdout) / 1024 / 1024, 2)
            except: pass

            if dl_size_mb > 2.0:
                url_ul = "https://speed.cloudflare.com/__up"
                safe_prox = shlex.quote(prox)
                cmd_ul = f"dd if=/dev/zero bs=1000 count=1000 2>/dev/null | curl -L -k -x {safe_prox} -s -w '%{{speed_upload}}' -o /dev/null --upload-file - {url_ul} --connect-timeout 5 --max-time 20"
                res_ul = subprocess.run(cmd_ul, shell=True, capture_output=True, text=True)
                try: ul_speed = round(float(res_ul.stdout) / 1024 / 1024, 2)
                except: pass

        # 3. SCORING
        score = 10.0
        if avg_ping > 800: score -= 4
        elif avg_ping > 400: score -= 2
        
        if jitter > 200: score -= 2
        elif jitter > 50: score -= 1
        
        if dl_size_mb > 0.5:
            if dl_speed < 0.5: score -= 3
            elif dl_speed < 2.0: score -= 1
            
        score = round(max(0.0, min(10.0, score)), 1)
        
        status_msg = "✅ Connected"
        if score >= 8: status_msg = "🚀 Excellent"
        elif score >= 5: status_msg = "⚖️ Normal"
        elif score < 5: status_msg = "⚠️ Weak"

        advanced_log(f"Result: {status_msg} | Ping: {avg_ping} | Score: {score}", "RESULT")

        return {
            "status": "OK", "ping": avg_ping, "jitter": jitter,
            "down": dl_speed, "up": ul_speed, "score": score,
            "protocol": outbound.get('protocol', 'unknown').upper(),
            "msg": status_msg
        }

    except Exception as e:
        advanced_log(f"Test Exception: {e}", "ERROR")
        return {"status": "Fail", "msg": f"❌ Error: {str(e)[:20]}", "score": 0}
    finally:
        # پاکسازی پروسه و فایل
        if proc:
            try: proc.terminate(); proc.wait(timeout=1)
            except: proc.kill()
        if os.path.exists(config_file):
            try: os.remove(config_file)
            except: pass

# ==============================================================================
# 🏁 MAIN ENTRY POINT (SMART PARSING)
# ==============================================================================
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument("link", help="Config Link")
    parser.add_argument("size", nargs="?", default="0.5", help="DL Size MB")
    args = parser.parse_args()

    advanced_log(f"Received Request: {args.link[:50]}...", "REQ")

    # 1. تنظیمات اولیه
    sync_system_time()
    install_xray()
    
    input_str = args.link
    try: dl_param = float(args.size)
    except: dl_param = 0.5

    configs_to_test = []
    sub_stats = {"upload": 0, "download": 0, "total": 0, "expire": 0, "title": "Unknown"}

    # تشخیص سابسکریپشن: اگر http باشد و حاوی پروتکل‌های تکی نباشد
    is_sub = input_str.startswith(('http://', 'https://')) and not any(p in input_str for p in ['vless://', 'vmess://', 'trojan://', 'ss://'])

    if is_sub:
        try:
            req = urllib.request.Request(input_str, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw_content = r.read().decode('utf-8', errors='ignore')
                advanced_log("Downloaded content.", "SUB")

                # استخراج هدرهای استاندارد (UserInfo)
                headers = r.info()
                user_info = headers.get('Subscription-Userinfo', '')
                if user_info:
                    for part in user_info.split(';'):
                        if '=' in part:
                            k, v = part.strip().split('=')
                            if k in sub_stats: sub_stats[k] = int(v)

                # --- 🚀 HTML PARSING LOGIC (PasarGuard Support) ---
                if "<html" in raw_content.lower():
                    advanced_log("HTML detected. Parsing...", "PARSE")
                    
                    # 1. استخراج نام ساب (Title)
                    # تلاش برای یافتن تایتل با خط تیره (Amirtn - ...)
                    title_match = re.search(r'<title>(.*?)\s*(?:-|\|)\s*.*?</title>', raw_content, re.IGNORECASE)
                    if not title_match:
                        # تلاش دوم: تایتل ساده
                        title_match = re.search(r'<title>(.*?)</title>', raw_content, re.IGNORECASE)
                    
                    if title_match:
                        clean_title = title_match.group(1).strip()
                        if clean_title: sub_stats['title'] = clean_title

                    # 2. استخراج لینک‌ها از value="..." یا value='...'
                    # این Regex تمام پروتکل‌ها را داخل کوتیشن پیدا می‌کند
                    links = re.findall(r'value=[\'"](vless://[^"\']+|vmess://[^"\']+|trojan://[^"\']+|ss://[^"\']+)[\'"]', raw_content)
                    
                    for i, l in enumerate(links):
                        name = f"Config_{i+1}"
                        # استخراج نام از هشتگ (#Name)
                        if '#' in l:
                            try: name = urllib.parse.unquote(l.split('#')[-1]).strip()
                            except: pass
                        
                        # اگر نام در هشتگ نبود، از پارامتر remarks استفاده کن
                        if name.startswith("Config_"):
                            try:
                                parsed = urllib.parse.urlparse(l)
                                qs = urllib.parse.parse_qs(parsed.query)
                                if 'remarks' in qs:
                                    name = qs['remarks'][0].strip()
                            except: pass
                            
                        # اگر باز هم نبود، از Hostname استفاده کن
                        if name.startswith("Config_"):
                            try:
                                parsed = urllib.parse.urlparse(l)
                                if parsed.hostname:
                                    name = f"{parsed.hostname}_{i+1}"
                            except: pass

                        # اگر vmess بود و هنوز نام نداشت، از داخل json (ps) بردار
                        if name.startswith("Config_") and l.startswith('vmess://'):
                            try:
                                b64 = l.replace('vmess://', '')
                                j = json.loads(decode_base64(b64))
                                if 'ps' in j and j['ps']: name = j['ps']
                            except: pass
                            
                        configs_to_test.append({"name": name, "link": l})
                        
                # --- STANDARD BASE64 PARSING ---
                else:
                    try: decoded = decode_base64(raw_content)
                    except: decoded = raw_content
                    patterns = r'(vless://[^\s\n]+|vmess://[^\s\n]+|trojan://[^\s\n]+|ss://[^\s\n]+)'
                    links = re.findall(patterns, decoded)
                    for i, l in enumerate(links):
                        name = f"Config_{i+1}"
                        if '#' in l:
                            try: name = urllib.parse.unquote(l.split('#')[-1]).strip()
                            except: pass
                        elif l.startswith('vmess://'):
                            try:
                                b64 = l.replace('vmess://', '')
                                j = json.loads(decode_base64(b64))
                                if 'ps' in j: name = j['ps']
                            except: pass
                        configs_to_test.append({"name": name, "link": l})

            advanced_log(f"Found {len(configs_to_test)} configs.", "PARSE")
            
            # چاپ خروجی متا برای بات (JSON)
            print(json.dumps({
                "type": "meta", 
                "total": len(configs_to_test), 
                "sub_info": sub_stats
            }, ensure_ascii=False), flush=True)

        except Exception as e:
            advanced_log(f"Sub Error: {e}", "ERROR")
            print(json.dumps({"status": "Fail", "msg": f"Sub Error: {str(e)}"}))
            sys.exit(1)
    else:
        # حالت کانفیگ تکی
        name = "Single_Config"
        if '#' in input_str:
             try: name = urllib.parse.unquote(input_str.split('#')[-1]).strip()
             except: pass
        elif input_str.startswith('vmess://'):
             try:
                 b64 = input_str.replace('vmess://', '')
                 j = json.loads(decode_base64(b64))
                 if 'ps' in j: name = j['ps']
             except: pass
             
        configs_to_test.append({"name": name, "link": input_str})

    # اجرای تست‌ها
    for cfg in configs_to_test:
        outbound = parse_xray_config(cfg['link'])
        
        if outbound:
            res = test_config(outbound, dl_param, config_name=cfg['name'])
            res['type'] = 'result'
            res['name'] = cfg['name']
            res['link'] = cfg['link']
            # چاپ خروجی نتیجه برای بات
            print(json.dumps(res, ensure_ascii=False), flush=True)
        else:
            advanced_log(f"Parse failed for {cfg['name']}", "WARN")
            print(json.dumps({"type": "result", "name": cfg['name'], "status": "Fail", "msg": "Parse Failed"}, ensure_ascii=False), flush=True)