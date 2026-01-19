import os, re, time, random, json, requests
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
# 需要续期服务器名称。只有一个服务器可留空
TARGET_NAME_CONFIG = os.getenv("TARGET_NAME", "loveMC") 

# 状态映射表
STATUS_MAP = {
    "Running": ["🟢", "Running"],
    "Starting": ["🟡", "Starting"],
    "Stopped": ["🔴", "Stopped"],
    "Offline": ["⚪", "Offline"],
    "Suspended": ["🚫", "Suspended"]
}

# ================= 工具函数 =================
def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def calculate_hours(date_str):
    """解析 ISO 时间换算为剩余小时数"""
    try:
        if not date_str: return 0
        clean_date = re.sub(r'\.\d+Z$', 'Z', str(date_str))
        expiry = datetime.fromisoformat(clean_date.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = (expiry - now).total_seconds() / 3600
        return max(0, int(diff))
    except:
        return 0

def fetch_api(driver, url, method="GET"):
    script = f"return fetch('{url}', {{method:'{method}'}}).then(r=>r.json()).catch(e=>({{success:false,message:e.toString()}}))"
    return driver.execute_script(script)

# Telegram 通知系统
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
        "maxed_out":"🈵 <b>GreatHost 已达上限</b>",
        "cooldown":"⏳ <b>GreatHost 还在冷却中</b>",
        "renew_failed":"⚠️ <b>GreatHost 续期未生效</b>",
        "business_error":"🚨 <b>GreatHost 脚本业务报错</b>",
        "proxy_error":"🚫 <b>GreatHost 代理预检失败</b>"
    }
    title = titles.get(kind, "‼️ <b>GreatHost 通知</b>")
    body = format_fields(fields)
    msg = f"{title}\n\n{body}\n📅 <b>时间:</b> {now_shanghai()}"
    send_telegram(msg)
    print("Notify:", title, "|", body.replace("\n"," | "))

# ================= 主流程 =================
def run_task():
    driver = None
    server_id = "未知"
    serverName = "未知名称"   # 预先初始化，避免 except 中未定义
    try:
        opts = Options()
        opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        
        sw = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL}} if PROXY_URL else None
        driver = webdriver.Chrome(options=opts, seleniumwire_options=sw)
        wait = WebDriverWait(driver, 25)

        # 1. 登录
        driver.get("https://greathost.es/login")
        wait.until(EC.presence_of_element_located((By.NAME,"email"))).send_keys(EMAIL)
        driver.find_element(By.NAME,"password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR,"button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))

        # 2. 获取 ID [按照您的要求从 API 获取]
        res = fetch_api(driver, "/api/servers")
        print("DEBUG /api/servers 返回：", json.dumps(res, indent=2, ensure_ascii=False))
        server_list = res.get("servers") if isinstance(res, dict) else res
        server_list = server_list or []
        target_server = next((s for s in server_list if s.get('name') == TARGET_NAME_CONFIG), None)
        if not target_server: raise Exception(f"未找到服务器: {TARGET_NAME_CONFIG}")
        server_id = target_server.get('id')

        # 3. 抓取 status (information 页面)
        driver.get(f"https://greathost.es/server-information-free.html?id={server_id}")
        time.sleep(5)
        info_res = fetch_api(driver, f"/api/servers/{server_id}/information")
        raw_status = info_res.get('status', 'Unknown')
        
        # 匹配详细状态图标和名称
        status_info = STATUS_MAP.get(raw_status.capitalize(), ["❓", raw_status])
        status_display = f"{status_info[0]} {status_info[1]}"

        # 4. 抓取续期前时间 (contract 页面)
        driver.get(f"https://greathost.es/contracts/{server_id}")
        time.sleep(5)
        contract_res = fetch_api(driver, f"/api/servers/{server_id}/contract")
        print("DEBUG /contract 返回：", json.dumps(contract_res, indent=2, ensure_ascii=False))

        # 先解析再打印 debug
        c_data = contract_res.get('contract', {}) or {}
        r_info = c_data.get('renewalInfo', {}) or {}

        serverName = c_data.get("serverName", serverName)
        before_h = calculate_hours(r_info.get('nextRenewalDate'))
        last_renew_str = r_info.get('lastRenewalDate')

        print("DEBUG serverName =", serverName)
        print("DEBUG nextRenewalDate =", r_info.get("nextRenewalDate"))
        print("DEBUG lastRenewalDate =", last_renew_str)
        print("DEBUG before_h =", before_h)

        # --- 冷却判定逻辑 (保持 30 分钟冷却) ---
        if last_renew_str:
            clean_last = re.sub(r'\.\d+Z$', 'Z', str(last_renew_str))
            try:
                last_time = datetime.fromisoformat(clean_last.replace('Z', '+00:00'))
            except Exception as e:
                print("DEBUG 解析 last_renew_str 失败:", clean_last, "错误:", e)
                last_time = None

            now_time = datetime.now(timezone.utc)
            minutes_passed = None
            if last_time:
                minutes_passed = (now_time - last_time).total_seconds() / 60

            # 调试输出：显示原始值与计算结果
            print("DEBUG 冷却检查原始 last_renew_str =", last_renew_str)
            print("DEBUG clean_last =", clean_last)
            print("DEBUG last_time (UTC) =", last_time)
            print("DEBUG now_time (UTC) =", now_time)
            print("DEBUG minutes_passed =", minutes_passed)

            if minutes_passed is not None and minutes_passed < 30:
                wait_min = int(30 - minutes_passed)
                print("DEBUG 处于冷却期，剩余分钟 =", wait_min)
                fields = [("📛","服务器名称", serverName),("🆔","ID",f"<code>{server_id}</code>"),("⏰","冷却倒计时",f"{wait_min} 分钟"),("📊","当前累计",f"{before_h}h"),("🚀","状态",status_display)]
                send_notice("cooldown", fields)
                return
            else:
                print("DEBUG 不在冷却期，minutes_passed =", minutes_passed)

        # 5. 执行续期 POST
        print(f"🚀 正在为 {TARGET_NAME_CONFIG} 发送续期请求...")
        renew_res = fetch_api(driver, f"/api/renewal/contracts/{server_id}/renew-free", method="POST")
        print("DEBUG renew_res:", json.dumps(renew_res, indent=2, ensure_ascii=False))

        # 6. 循环等待后台写入 nextRenewalDate（最多等 15 秒）
        after_h = 0
        for _ in range(5):  # 每次等 3 秒，总共最多 15 秒
            time.sleep(3)
            renew_contract = fetch_api(driver, f"/api/servers/{server_id}/contract")

            # 安全打印原始返回（避免 json.dumps 抛异常）
            try:
                print("DEBUG loop raw:", json.dumps(renew_contract, ensure_ascii=False))
            except Exception:
                print("DEBUG loop raw (non-serializable):", type(renew_contract), str(renew_contract)[:500])

            # 兼容两种返回结构：{contract: {...}} 或 直接 contract 对象
            renew_c = {}
            if isinstance(renew_contract, dict):
                renew_c = renew_contract.get('contract') or renew_contract
                if not isinstance(renew_c, dict):
                    renew_c = {}

            try:
                print("DEBUG loop contract:", json.dumps(renew_c, ensure_ascii=False))
            except Exception:
                print("DEBUG loop contract (non-serializable):", type(renew_c))

            next_dt = None
            if isinstance(renew_c, dict):
                next_dt = renew_c.get('renewalInfo', {}).get('nextRenewalDate')

            after_h = calculate_hours(next_dt)

            print("DEBUG 循环检查 after_h =", after_h, " nextRenewalDate =", next_dt)
            if after_h > before_h:
                break


        # 7. 智能判定判定部分 
        is_success = after_h > before_h
        print("DEBUG 判定：before_h =", before_h, "after_h =", after_h, "is_success =", is_success)
        msg_str = str(renew_res.get('message', '')).lower()
        has_limit_msg = "5 días" in msg_str or "limit" in msg_str
      
        has_reached_threshold = (before_h >= 108 and after_h <= before_h)
        is_maxed = has_limit_msg or (has_reached_threshold and renew_res.get('success'))

        if is_success:
            fields = [
                ("📛","服务器名称", serverName),
                ("🆔","ID", f"<code>{server_id}</code>"),
                ("⏰","增加时间", f"{before_h} ➔ {after_h}h"),
                ("🚀","服务器状态", status_display),
                ("💰","当前金币", str(c_data.get('userCoins', 0)))
            ]
            send_notice("renew_success", fields)

        elif is_maxed:
            fields = [
                ("📛","服务器名称", serverName),
                ("🆔","ID", f"<code>{server_id}</code>"),
                ("⏰","剩余时间", f"{after_h}h"),
                ("🚀","服务器状态", status_display),
                ("💡","提示", "已近120h上限，暂无需续期。")
            ]
            send_notice("maxed_out", fields)

        else:
            fields = [
                ("📛","服务器名称", serverName),
                ("🆔","ID", f"<code>{server_id}</code>"),
                ("⏰","剩余时间", f"{before_h}h"),
                ("🚀","服务器状态", status_display),
                ("💡","提示", "时间未增加，请手动确认。")
            ]
            send_notice("renew_failed", fields)


    except Exception as e:
        err = str(e).replace('<','[').replace('>',']')
        print("Runtime error:", err)
        # 使用已初始化的 serverName 以避免二次异常
        send_notice("business_error", [("📛","服务器名称", serverName),("🆔","ID",f"<code>{server_id}</code>"),("❌","详情",f"<code>{err}</code>")])
    finally:
        if driver: driver.quit()

if __name__ == "__main__":
    run_task()
