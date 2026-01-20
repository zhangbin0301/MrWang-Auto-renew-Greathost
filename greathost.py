import os, re, time, random, requests, json
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= 配置区 =================
EMAIL = os.getenv("GREATHOST_EMAIL", "")
PASSWORD = os.getenv("GREATHOST_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# 代理sock5可留空
PROXY_URL = os.getenv("PROXY_URL", "")

# 目标服务器名
TARGET_NAME_CONFIG = os.getenv("TARGET_NAME", "loveMC")

STATUS_MAP = {
    "running": ["🟢", "Running"],
    "starting": ["🟡", "Starting"],
    "stopped": ["🔴", "Stopped"],
    "offline": ["⚪", "Offline"],
    "suspended": ["🚫", "Suspended"]
}

# ================= 工具函数 =================
def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def calculate_hours(date_str):
    try:
        if not date_str: return 0
        clean_date = re.sub(r'\.\d+Z$', 'Z', date_str)
        expiry = datetime.fromisoformat(clean_date.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = (expiry - now).total_seconds() / 3600
        return max(0, int(diff))
    except Exception as e:
        print(f"⚠️ 时间解析失败: {e}")
        return 0

def fetch_api(driver, url, method="GET"):
    script = f"return fetch('{url}', {{method:'{method}'}}).then(r=>r.json()).catch(e=>({{success:false,message:e.toString()}}))"
    res = driver.execute_script(script)
    print(f"📡 API 调用 [{method}] {url}")
    return res

def send_notice(kind, fields):
    titles = {
        "renew_success": "🎉 <b>GreatHost 续期成功</b>",
        "maxed_out": "🈵 <b>GreatHost 已达上限</b>",
        "cooldown": "⏳ <b>GreatHost 还在冷却中</b>",
        "renew_failed": "⚠️ <b>GreatHost 续期未生效</b>",
        "error": "🚨 <b>GreatHost 脚本报错</b>"
    }
    title = titles.get(kind, "‼️ <b>GreatHost 通知</b>")
    body = "\n".join([f"{e} {l}: {v}" for e, l, v in fields])
    msg = f"{title}\n\n{body}\n📅 时间: {now_shanghai()}"
    
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                          data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
        except: pass

# ================= 主流程 =================
def run_task():
    driver = None
    target_name = "未知" 
    server_id = "未知"
    login_ip = "Unknown"
    target_name = TARGET_NAME_CONFIG
    
    try:
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        driver = webdriver.Chrome(options=opts, seleniumwire_options={'proxy': {'http': PROXY_URL, 'https': PROXY_URL}} if PROXY_URL else None)
        wait = WebDriverWait(driver, 25)

        # 0. 登入 IP 打印
        try:
            driver.get("https://api.ipify.org?format=json")
            login_ip = json.loads(driver.find_element(By.TAG_NAME, "body").text).get('ip', 'Unknown')
            print(f"🌐 登入 IP: {login_ip}")
        except: print("🌐 登入 IP: 无法获取")

        # 1. 登录
        print(f"🔑 正在登录: {EMAIL[:3]}***...")
        driver.get("https://greathost.es/login")
        wait.until(EC.presence_of_element_located((By.NAME,"email"))).send_keys(EMAIL)
        driver.find_element(By.NAME,"password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR,"button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))

        # 2. 获取服务器列表并锁定
        res = fetch_api(driver, "/api/servers")
        server_list = res.get('servers', [])
        target_server = next((s for s in server_list if s.get('name') == target_name), None)
        
        if not target_server: raise Exception(f"未找到服务器 {target_name}")
        server_id = target_server.get('id')
        print(f"✅ 已锁定目标服务器: {target_name} (ID: {server_id})")
        
        # 3. 获取实时服务器状态（Running Stop...）
        info = fetch_api(driver, f"/api/servers/{server_id}/information")
        real_status = info.get('status', 'unknown').lower()
        icon, status_name = STATUS_MAP.get(real_status, ["❓", real_status])
        status_disp = f"{icon} {status_name}"
        print(f"📋 状态核对: {target_name} | {status_disp}")

        # 4. 时间检查与冷却判定
        driver.get(f"https://greathost.es/contracts/{server_id}")
        time.sleep(2)
        
        # 在Renew前抓取后台API数据
        contract_data = fetch_api(driver, f"/api/renewal/contracts/{server_id}")
        print(f"DEBUG: 原始合同数据 -> {str(contract_data)[:100]}...")
        
        renewal_info = contract_data.get('contract', {}).get('renewalInfo') or contract_data.get('renewalInfo', {})
        before_h = calculate_hours(renewal_info.get('nextRenewalDate'))
        
        btn = wait.until(EC.presence_of_element_located((By.ID, "renew-free-server-btn")))
        btn_text = btn.text.strip()
        print(f"🔘 按钮状态: '{btn_text}' | 剩余: {before_h}h")
        
        if "Wait" in btn_text:
            m = re.search(r"Wait\s+(\d+\s+\w+)", btn_text)
            wait_time = m.group(1) if m else btn_text
            send_notice("cooldown", [
                ("📛", "服务器名称", target_name),
                ("🆔", "ID", f"<code>{server_id}</code>"),
                ("⏳", "冷却时间", wait_time),
                ("📊", "当前累计", f"{before_h}h"),
                ("🚀", "服务器状态", status_disp)
            ])
            return

        # 5. 执行续期
        print(f"🚀 正在执行续期 POST...")
        renew_res = fetch_api(driver, f"/api/renewal/contracts/{server_id}/renew-free", method="POST")

        # 续期成功后，抓新日期等信息( details 字段下)
        is_success = renew_res.get('success', False)      
        res_message = renew_res.get('message', '无返回消息')
        after_date = renew_res.get('details', {}).get('nextRenewalDate')
        print(f"📡 续期响应结果: {is_success} | Date='{after_date}' | Message='{res_message}'")
        
        # 确保 after_h 在失败时不会变成 0
        if is_success and after_date:
            after_h = calculate_hours(after_date)
        else:
            after_h = before_h

        # 6. 判定并发送通知
        if is_success and after_h > before_h:
            send_notice("renew_success", [
                ("📛", "服务器名称", target_name),
                ("🆔", "ID", f"<code>{server_id}</code>"),
                ("⏰", "增加时间", f"{before_h} ➔ {after_h}h"),
                ("🚀", "服务器状态", status_disp),
                ("🌐", "登入 IP", f"<code>{login_ip}</code>")
            ])
        elif "5 d" in str(renew_res.get('message', '')) or (before_h > 108):
            send_notice("maxed_out", [
                ("📛", "服务器名称", target_name),
                ("🆔", "ID", f"<code>{server_id}</code>"),
                ("⏰", "剩余时间", f"{after_h}h"),
                ("🚀", "服务器状态", status_disp),
                ("💡", "提示", res_message),
                ("🌐", "登入 IP", f"<code>{login_ip}</code>")
            ])
        else:
            send_notice("renew_failed", [
                ("📛", "服务器名称", target_name),
                ("🆔", "ID", f"<code>{server_id}</code>"),
                ("⏰", "剩余时间", f"{before_h}h"),
                ("💡", "提示", res_message)
            ])

    except Exception as e:
        print(f"🚨 运行异常: {e}")
        send_notice("error", [("📛", "服务器名称", target_name), ("❌", "故障", f"<code>{str(e)[:100]}</code>")])
    finally:
        if driver: driver.quit()

if __name__ == "__main__":
    run_task()
