import os, re, time, random, requests
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Config
EMAIL = os.getenv("GREATHOST_EMAIL", "")
PASSWORD = os.getenv("GREATHOST_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PROXY_URL = os.getenv("PROXY_URL", "")

STATUS_MAP = {
    "Running": ["🟢", "运行中"],
    "Starting": ["🟡", "启动中"],
    "Stopped": ["🔴", "已关机"],
    "Offline": ["⚪", "离线"],
    "Suspended": ["🚫", "已暂停/封禁"]
}

def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def mask_host(h):
    if not h: return "Unknown"
    if ":" in h:
        p = h.split(':')
        return f"{p[0]}:{p[1]}:****:{p[-1]}" if len(p) > 3 else f"{h[:9]}****"
    parts = h.split('.')
    if len(parts) == 4: return f"{parts[0]}.{parts[1]}.***.{parts[3]}"
    if len(parts) >= 3: return f"{parts[0]}.****.{parts[-1]}"
    return f"{h[:4]}****"

def get_proxy_expected_host():
    raw = (os.getenv("PROXY_URL") or "").strip()
    if not raw: return None
    try:
        tmp = raw if "://" in raw else f"http://{raw}"
        host = urlparse(tmp).hostname
        return host.lower().replace("[","").replace("]","") if host else None
    except:
        return None

EXPECTED_HOST = get_proxy_expected_host()

# Telegram
def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    s = requests.Session(); s.trust_env = False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        s.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        print("TG send failed:", e)

def format_fields(fields):
    return "\n".join(f"{emoji} <b>{label}:</b> {value}" for emoji,label,value in fields)

def send_notice(kind, fields):
    titles = {
        "renew_success":"🎉 <b>GreatHost 续期成功</b>",
        "maxed_out":"⚠️ <b>GreatHost 已达上限</b>",
        "cooldown":"⏳ <b>GreatHost 还在冷却中</b>",
        "renew_failed":"⚠️ <b>GreatHost 续期未生效</b>",
        "business_error":"🚨 <b>GreatHost 脚本业务报错</b>",
        "proxy_error":"🚨 <b>GreatHost 代理预检失败</b>"
    }
    title = titles.get(kind, "ℹ️ <b>GreatHost 通知</b>")
    body = format_fields(fields)
    msg = f"{title}\n\n{body}\n📅 <b>时间:</b> {now_shanghai()}"
    send_telegram(msg)
    print("Notify:", title, "|", body.replace("\n"," | "))

# Proxy check (3 steps)
def check_proxy_ip(driver):
    if not PROXY_URL.strip():
        print("No proxy configured, skip proxy check.")
        return True
    proxy = {"http": PROXY_URL, "https": PROXY_URL}
    now = now_shanghai()
    try:
        r = requests.get("https://api64.ipify.org?format=json", proxies=proxy, timeout=12)
        current_ip = r.json().get("ip","").lower()
        print("Proxy IP:", current_ip)
        if EXPECTED_HOST:
            match_full = (EXPECTED_HOST in current_ip) or (current_ip in PROXY_URL.lower())
            ipv6_match = (":" in current_ip and ":" in EXPECTED_HOST and current_ip.split(':')[:4] == EXPECTED_HOST.split(':')[:4])
            if not (match_full or ipv6_match):
                m_exp, m_cur = mask_host(EXPECTED_HOST), mask_host(current_ip)
                raise Exception(f"BLOCK_ERR|{m_exp}|{m_cur}")
        driver.set_page_load_timeout(30)
        driver.get("https://api.ipify.org?format=json")
        return True
    except Exception as e:
        clean = str(e).replace('<','[').replace('>',']')
        if "BLOCK_ERR" in clean:
            _, m_exp, m_cur = clean.split('|')
            msg = (f"🚨 <b>GreatHost IP 校验拦截</b>\n\n"
                   f"❌ <b>配置代理:</b> <code>{m_exp}</code>\n"
                   f"❌ <b>实际出口:</b> <code>{m_cur}</code>\n"
                   f"⚠️ <b>警告:</b> 代理已偏离\n📅 <b>时间:</b> {now}")
            send_telegram(msg); raise Exception(clean)
        else:
            msg = (f"🚨 <b>GreatHost 代理预检失败</b>\n\n"
                   f"❌ <b>详情:</b> <code>{clean}</code>\n📅 <b>时间:</b> {now}")
            send_telegram(msg); raise Exception(clean)

# Browser helpers
def get_browser():
    # 1. 基础浏览器参数配置
    opts = Options()
    opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage"); opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    # 2. 只有当代理为空时，直连
    if PROXY_URL and str(PROXY_URL).strip().lower() != "none":
        sw = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL, 'no_proxy': 'localhost,127.0.0.1'}}
        print(f"Log: Browser starting with proxy.")
        return webdriver.Chrome(options=opts, seleniumwire_options=sw)
    else:        
        print("Log: PROXY_URL is empty, launching in direct mode.")
        return webdriver.Chrome(options=opts)

def safe_send_keys(el, text):
    try: el.clear()
    except: pass
    el.send_keys(text); time.sleep(0.12)

def safe_click(driver, el):
    try: el.click()
    except:
        try: driver.execute_script("arguments[0].click();", el)
        except: raise

def click_button(driver, el, desc, js_selector=None):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        time.sleep(random.uniform(1.0,2.0))
        safe_click(driver, el); time.sleep(2); print("Clicked:", desc); return True
    except Exception as e:
        print("Click failed:", e, "try JS")
        try:
            if js_selector:
                driver.execute_script(f"document.querySelector('{js_selector}').click();")
            else:
                driver.execute_script("arguments[0].click();", el)
            time.sleep(2); return True
        except Exception as e2:
            print("JS click failed:", e2); return False

def perform_step(driver, wait, desc, locator, js_selector=None):
    try:
        el = wait.until(EC.element_to_be_clickable(locator))
        return click_button(driver, el, desc, js_selector)
    except Exception as e:
        print(desc, "failed:", e); return False

# Core actions
def login(driver, wait):
    driver.get("https://greathost.es/login")
    e = wait.until(EC.presence_of_element_located((By.NAME,"email")))
    try: click_button(driver, e, "email focus")
    except: pass
    time.sleep(0.2); safe_send_keys(e, EMAIL)
    p = wait.until(EC.presence_of_element_located((By.NAME,"password")))
    try: click_button(driver, p, "password focus")
    except: pass
    time.sleep(0.2); safe_send_keys(p, PASSWORD)
    time.sleep(random.uniform(0.6,1.2))
    s = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,"button[type='submit']")))
    safe_click(driver, s); wait.until(EC.url_contains("/dashboard")); print("Logged in")

def simulate_human(driver, wait):
    if random.random() > 0.5:
        driver.get("https://greathost.es/services"); time.sleep(random.randint(3,6))
        driver.get("https://greathost.es/dashboard"); wait.until(EC.url_contains("/dashboard"))
        time.sleep(random.uniform(0.8,2.0))

def go_to_details(driver, wait):
    perform_step(driver, wait, "Billing icon", (By.CLASS_NAME,'btn-billing-compact'), ".btn-billing-compact")
    perform_step(driver, wait, "View Details", (By.LINK_TEXT,'View Details'), "a[href*='details']")
    return driver.current_url.split('/')[-1] or "unknown"

def get_hours(driver, selector="#accumulated-time"):
    for _ in range(6):
        try:
            text = driver.execute_script(f"return document.querySelector('{selector}').textContent;") or driver.find_element(By.CSS_SELECTOR, selector).text
            num = int(re.sub(r'\D', '', text)) if re.search(r'\d', text) else 0
            if num > 0: return num, text
        except: text = ""
        time.sleep(3)
    return 0, text

def get_error_msg(driver):
    try: return driver.find_element(By.CSS_SELECTOR, '.toast-error, .alert-danger, .toast-message').text or ""
    except: return ""

def renew_click(driver, wait):
    perform_step(driver, wait, "Renew button", (By.ID,'renew-free-server-btn'))
    time.sleep(2); msg = get_error_msg(driver) # 点击后只等 2s 看有没有报错提示
    # 删掉原来的 time.sleep(20) 和 driver.refresh()
    return msg

def confirm_and_start(driver, wait):
    final = "运行正常"; started = False
    try:
        driver.get("https://greathost.es/dashboard")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME,'server-status-indicator')))
        time.sleep(1.5)
        ind = driver.find_element(By.CLASS_NAME,'server-status-indicator')
        final = ind.get_attribute('title') or "Unknown"
    except Exception as e:
        print("Final status fetch failed:", e); final = "确认失败"
    low = final.lower()
    if any(x in low for x in ['stopped','offline']):
        print("Final state offline/stopped, try start")
        started = perform_step(driver, wait, "Start button", (By.CSS_SELECTOR,'button.btn-start, .action-start'), "button.btn-start, .action-start")
    return final, started

# Main
def run_task():
    time.sleep(random.randint(1,60))
    driver = None; server_id = "未知"; before = 0; after = 0; status_display = "🟢 运行正常"
    try:
        # 核心修改：确保 get_browser 内部能处理 PROXY_URL 为空的情况
        # 如果 get_browser 是你定义的，请确保它内部有 if PROXY_URL: options.add_argument... 的判断
        driver = get_browser() 
        
        # 如果代理为空，跳过预检（避免在直连模式下报代理预检失败）
        if globals().get('PROXY_URL'):
            check_proxy_ip(driver)
        
        wait = WebDriverWait(driver, 15)
        login(driver, wait)
        simulate_human(driver, wait)

        server_id = go_to_details(driver, wait)
        before, _ = get_hours(driver)
        print("Before hours:", before)

        renew_btn = wait.until(EC.presence_of_element_located((By.ID,"renew-free-server-btn")))
        btn_html = renew_btn.get_attribute('innerHTML') or ""
        if 'Wait' in btn_html:
            m = re.search(r'\d+', btn_html); wt = m.group(0) if m else "??"
            fields = [("🆔","服务器ID",f"<code>{server_id}</code>"),("⏰","冷却时间",f"{wt} 分钟"),("📊","当前累计",f"{before}h"),("🚀","服务器状态",status_display)]
            send_notice("cooldown", fields)
            return # finally 会处理 driver.quit()

        err_msg = renew_click(driver, wait)
        after, _ = get_hours(driver)
        print("After hours:", after)
        
        if after == before:                
            time.sleep(15)
            try: 
                driver.refresh()
                after, _ = get_hours(driver)
                print(f"After hours (retry): {after}")
            except: pass

        print(f"Final after hours used for 判定: {after}")
        final_status, started_flag = confirm_and_start(driver, wait)
        if started_flag:
            icon, name = STATUS_MAP.get(final_status, ["❓", final_status])
            status_display = f"✅ 已触发启动 ({icon} {name})"
        else:
            icon, name = STATUS_MAP.get(final_status, ["🟢", "运行正常"])
            status_display = f"{icon} {name}"

        is_success = after > before
        is_maxed = ("5 días" in err_msg) or (before > 108 and after == before)
                
        if is_success:
            fields = [("🆔","ID",f"<code>{server_id}</code>"),("⏰","增加时间",f"{before} ➔ {after}h"),("🚀","服务器状态",status_display)]
            send_notice("renew_success", fields)
        elif is_maxed:
            fields = [("🆔","ID",f"<code>{server_id}</code>"),("⏰","剩余时间",f"{after}h"),("🚀","服务器状态",status_display),("💡","提示","已近120h上限，暂无需续期。")]
            send_notice("maxed_out", fields)
        else:
            fields = [("🆔","ID",f"<code>{server_id}</code>"),("⏰","剩余时间",f"{before}h"),("🚀","服务器状态",status_display),("💡","提示","时间未增加，请手动确认。")]
            send_notice("renew_failed", fields)

    except Exception as e:
        err = str(e).replace('<','[').replace('>',']')
        print("Runtime error:", err)
        # 关键过滤：增加 "None" 和 "specification" 拦截代理变量为空导致的报错
        proxy_keys = ["BLOCK_ERR", "代理预检", "Pool", "Timeout", "None", "specification"]
        if all(k not in err for k in proxy_keys):
            try: loc = driver.current_url if driver else "未知"
            except: loc = "获取失败"
            send_notice("business_error", [("🆔","ID",f"<code>{server_id}</code>"),("❌","详情",f"<code>{err}</code>"),("📍","位置",loc)])
        else: print("Proxy/Network/Env error, skip business notify.")
    finally:
        if driver:
            try: driver.quit(); print("Browser closed")
            except: pass

if __name__ == "__main__":
    run_task()
