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
PROXY_URL = os.getenv("PROXY_URL", "")

STATUS_MAP = {
    "Running": ["🟢", "运行中"],
    "Starting": ["🟡", "启动中"],
    "Stopped": ["🔴", "已关机"],
    "Offline": ["⚪", "离线"],
    "Suspended": ["🚫", "已暂停/封禁"]
}

# ================= 工具函数 =================
def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def calculate_hours(date_str):
    try:
        if not date_str: return 0
        expiry = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return max(0, int((expiry - now).total_seconds() / 3600))
    except: return 0

def fetch_api(driver, url, method="GET"):
    """执行 JS 抓取 API 并打印调试信息"""
    script = f"return fetch('{url}', {{method:'{method}'}}).then(r=>r.json()).catch(e=>({{success:false,message:e.toString()}}))"
    res = driver.execute_script(script)
    print(f"📡 API 调用 [{method}] {url}")
    return res

def send_notice(kind, fields):
    titles = {"renew_success":"🎉 <b>续期成功</b>", "maxed_out":"🈵 <b>已达上限</b>", 
              "cooldown":"⏳ <b>还在冷却</b>", "renew_failed":"⚠️ <b>续期未生效</b>", "error":"🚨 <b>脚本报错</b>"}
    body = "\n".join([f"{e} <b>{l}:</b> {v}" for e,l,v in fields])
    msg = f"{titles.get(kind, '‼️ 通知')}\n\n{body}\n📅 <b>时间:</b> {now_shanghai()}"
    if TELEGRAM_BOT_TOKEN:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                          data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
        except: pass

# ================= 主流程 =================
def run_task():
    driver = None
    target_name = "loveMC"  # 设定目标服务器名称
    server_id = "未知"
    
    try:
        opts = Options()
        opts.add_argument("--headless=new")
        driver = webdriver.Chrome(options=opts, seleniumwire_options={'proxy': {'http': PROXY_URL, 'https': PROXY_URL}} if PROXY_URL else None)
        wait = WebDriverWait(driver, 25)

        # 1. 登录
        print(f"🔑 正在登录: {EMAIL}...")
        driver.get("https://greathost.es/login")
        wait.until(EC.presence_of_element_located((By.NAME,"email"))).send_keys(EMAIL)
        driver.find_element(By.NAME,"password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR,"button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))

        # 2. 获取服务器列表并过滤目标 [修正点]
        res = fetch_api(driver, "/api/servers")
        server_list = res.get('servers', []) # 从字典中提取列表
        
        # 寻找名为 loveMC 的服务器
        target_server = next((s for s in server_list if s.get('name') == target_name), None)
        
        if not target_server:
            raise Exception(f"在账号下未找到名为 '{target_name}' 的服务器")
            
        server_id = target_server.get('id')
        print(f"✅ 已锁定目标服务器: {target_name} (ID: {server_id})")
        
        # 3. 获取实时状态
        info = fetch_api(driver, f"/api/servers/{server_id}/information")
        real_status = info.get('status', 'Unknown')
        print(f"📋 状态核对: {target_name} 当前状态为 {real_status}")

        # 4. 合同页预检
        driver.get(f"https://greathost.es/contracts/{server_id}")
        time.sleep(2)
        
        contract = fetch_api(driver, f"/api/servers/{server_id}/contract")
        before_h = calculate_hours(contract.get('renewalInfo', {}).get('nextRenewalDate'))
        
        btn = wait.until(EC.presence_of_element_located((By.ID, "renew-free-server-btn")))
        btn_text = btn.text.strip()
        print(f"🔘 按钮状态: '{btn_text}' | 剩余: {before_h}h")
        
        if "Wait" in btn_text:
            m = re.search(r"Wait\s+(\d+\s+\w+)", btn_text)
            wait_time = m.group(1) if m else btn_text
            send_notice("cooldown", [("📛","名称",target_name), ("⏳","等待",wait_time), ("📊","当前",f"{before_h}h")])
            return

        # 5. 执行续期
        print(f"🚀 正在为 {target_name} 执行续期 POST...")
        renew_res = fetch_api(driver, f"/api/renewal/contracts/{server_id}/renew-free", method="POST")
        
        is_success = renew_res.get('success', False)
        hours_added = renew_res.get('details', {}).get('hoursAdded', 0)
        after_h = calculate_hours(renew_res.get('details', {}).get('nextRenewalDate')) or before_h
        
        # 图标映射
        icon, status_name = STATUS_MAP.get(real_status.capitalize(), ["🟢", real_status])
        status_disp = f"{icon} {status_name}"

        # 6. 结果判定
        if is_success and hours_added > 0:
            send_notice("renew_success", [("📛","名称",target_name), ("⏰","变化",f"{before_h} ➔ {after_h}h"), ("🚀","状态",status_disp)])
        elif "5 d" in str(renew_res.get('message', '')) or (before_h > 110):
            send_notice("maxed_out", [("📛","名称",target_name), ("⏰","余额",f"{after_h}h"), ("🚀","状态",status_disp), ("💡","提示","已达5天上限")])
        else:
            send_notice("renew_failed", [("📛","名称",target_name), ("💡","原因",renew_res.get('message','未知失败'))])

    except Exception as e:
        print(f"🚨 运行异常: {e}")
        send_notice("error", [("📛","目标",target_name), ("❌","故障",f"<code>{str(e)[:100]}</code>")])
    finally:
        if driver: driver.quit()

if __name__ == "__main__":
    run_task()
