import time
import os
import re
import json
import random
import requests
from datetime import datetime
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ================= 环境变量获取 =================
EMAIL = os.getenv("GREATHOST_EMAIL") or ""
PASSWORD = os.getenv("GREATHOST_PASSWORD") or ""
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or ""
# sock5代码，不需要留空值 62行要填上IP头
PROXY_URL = os.getenv("PROXY_UR") or ""

def send_telegram(msg_type_or_text, error_msg=None):    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    
    # 构造最终发送的消息
    if msg_type_or_text == "fail" and error_msg:
        message = f"🚨 <b>代理检查失败</b>\n<code>{error_msg}</code>"
    else:
        message = msg_type_or_text

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=payload, timeout=10)
    except Exception as e: 
        print(f"Telegram 发送失败: {e}")

def get_now_shanghai():
    return datetime.now().strftime('%Y/%m/%d %H:%M:%S')

def check_proxy_ip(driver):
    """【熔断逻辑】检测当前代理 IP (防止代理失效导致直连)"""
    if not PROXY_URL.strip():
        print("🌍 [Check] 未设置代理，跳过代理 IP 检查。")
        return True

    print("🌍 [Check] 正在检测代理 IP...")
    try:
        driver.set_page_load_timeout(20)
        driver.get("https://api.ipify.org?format=json")

        WebDriverWait(driver, 10).until(
            lambda d: "{" in d.find_element(By.TAG_NAME, "body").text
        )
        ip_body = driver.find_element(By.TAG_NAME, "body").text
        ip_info = json.loads(ip_body)

        current_ip = ip_info.get('ip')
        print(f"✅ 当前出口 IP: {current_ip}")

        if not current_ip.startswith("138.68"):
            print(f"⚠️ 警告: IP ({current_ip}) 似乎不是预期的代理 IP！")

        return True

    except Exception as e:
        print(f"❌ 无法检测 IP (可能是代理连接超时): {e}")
        # ⭐ 关键：代理不通 → 发送失败通知
        send_telegram("fail", error_msg=f"代理检查失败: {e}")
        # ⭐ 关键：抛异常终止脚本
        raise Exception(f"Proxy Check Failed: {e}")

def get_browser():
    sw_options = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL, 'no_proxy': 'localhost,127.0.0.1'}}
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options, seleniumwire_options=sw_options)

def run_task():
    # 随机延迟启动
    wait_time = random.randint(1, 300)
    print(f"⏳ 为了模拟真人，随机等待 {wait_time} 秒后启动...")
    time.sleep(wait_time)

    driver = None
    server_started = False
    try:
        driver = get_browser()
        
        # === 代理熔断检查 ===
        check_proxy_ip(driver)

        # === 登录流程 ===
        wait = WebDriverWait(driver, 15)
        print("🔑 正在执行登录...")
        driver.get("https://greathost.es/login")
        wait.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
        driver.find_element(By.NAME, "password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))
        print("✅ 登录成功！")

        # === 2. 状态检查与自动开机 (JS 1:1) ===
        print("📊 正在检查服务器实时状态...")
        try:
            status_text = driver.find_element(By.CSS_SELECTOR, '.status-text, .server-status').text or 'unknown'
        except: status_text = 'unknown'
        status_lower = status_text.strip().lower()

        if any(x in status_lower for x in ['offline', 'stopped', '离线']):
            print(f"⚡ 检测到离线 [{status_text}]，尝试触发启动...")
            try:
                start_btn = driver.find_element(By.CSS_SELECTOR, 'button.btn-start[title="Start Server"]')
                if start_btn.is_displayed() and start_btn.get_attribute('disabled') is None:
                    start_btn.click()
                    server_started = True
                    print("✅ 启动指令已发出")
                    time.sleep(1) # waitForTimeout(1000)
                else:
                    print("⚠️ 启动按钮可能正在冷却或未找到，跳过启动。")
            except:
                print("ℹ️ 辅助启动步骤轻微异常，忽略并继续后续续期...")
        else:
            print(f"ℹ️ 服务器状态 [{status_text}] 正常，无需启动。")

        # === 3. 点击 Billing 图标进入账单页 (JS 1:1) ===
        print("🔍 点击 Billing 图标...")
        driver.find_element(By.CLASS_NAME, 'btn-billing-compact').click()
        print("⏳ 已进入 Billing，等待3秒...")
        time.sleep(3)

        # === 4. 点击 View Details 进入详情页 (JS 1:1) ===
        print("🔍 点击 View Details...")
        driver.find_element(By.LINK_TEXT, 'View Details').click()
        print("⏳ 已进入详情页，等待3秒...")
        time.sleep(3)

        # === 5. 提前提取 ID (JS 1:1) ===
        server_id = driver.current_url.split('/')[-1] or 'unknown'
        print(f"🆔 解析到 Server ID: {server_id}")

        # === 6. 等待异步数据加载 (JS 1:1) ===
        time_selector = "#accumulated-time"
        try:
            wait.until(lambda d: re.search(r'\d+', d.find_element(By.CSS_SELECTOR, time_selector).text) and d.find_element(By.CSS_SELECTOR, time_selector).text.strip() != '0 hours')
        except:
            print("⚠️ 初始时间加载超时或为0")

        # === 7. 获取当前状态 (JS 1:1) ===
        before_hours_text = driver.find_element(By.CSS_SELECTOR, time_selector).text
        before_hours = int(re.sub(r'[^0-9]', '', before_hours_text)) or 0

        # === 8. 定位按钮状态 (JS 1:1) ===
        renew_btn = driver.find_element(By.ID, 'renew-free-server-btn')
        btn_content = renew_btn.get_attribute('innerHTML')

        # === 9. 逻辑判定 (JS 1:1) ===
        print(f"🆔 ID: {server_id} | ⏰ 目前: {before_hours}h | 🔘 状态: {'冷却中' if 'Wait' in btn_content else '可续期'}")

        if 'Wait' in btn_content:
            wait_time = re.search(r'\d+', btn_content).group(0) or "??"
            message = (f"⏳ <b>GreatHost 还在冷却中</b>\n\n"
                       f"🆔 <b>服务器ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>冷却时间:</b> {wait_time} 分钟\n"
                       f"📊 <b>当前累计:</b> {before_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {'✅ 已触发启动' if server_started else '运行中'}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}")
            send_telegram(message)
            return

        # === 10. 执行续期 (模拟真人) (JS 1:1) ===
        print("⚡ 启动模拟真人续期流程...")
        try:
            # 1. 模拟滚动
            driver.execute_script(f"window.scrollBy(0, {random.randint(50, 200)});")
            print("👉 模拟页面滚动...")
            
            # 2. 随机发呆
            time.sleep(random.uniform(2, 5))

            # 3. 模拟鼠标平滑移动
            ActionChains(driver).move_to_element_with_offset(renew_btn, random.uniform(-5, 5), random.uniform(-5, 5)).perform()
            print("👉 鼠标平滑轨迹模拟完成")

            # 4. 执行“三保险”点击
            # [1/3] 物理点击
            renew_btn.click()
            print("👉 [1/3] 物理点击已执行")

            # [2/3] DOM 事件注入
            driver.execute_script("const btn=document.querySelector('#renew-free-server-btn');if(btn){['mouseenter','mousedown','mouseup','click'].forEach(evt=>{btn.dispatchEvent(new MouseEvent(evt,{bubbles:true,cancelable:true,view:window}))});}")
            print("👉 [2/3] 事件链路注入完成")

            # [3/3] 逻辑函数直接调用
            driver.execute_script("if(typeof renewFreeServer==='function'){renewFreeServer();}")
            print("👉 [3/3] 函数触发检查完毕")

        except Exception as e:
            print(f"🚨 点击过程异常: {e}")

        # === 11. 深度等待同步 (JS 1:1) ===
        print("⏳ 正在进入 20 秒深度等待，确保后端写入数据...")
        time.sleep(20)

        error_msg = ""
        try:
            error_msg = driver.find_element(By.CSS_SELECTOR, '.toast-error, .alert-danger, .toast-message').text
            if error_msg: print(f"🔔 页面反馈信息: {error_msg}")
        except: pass

        print("🔄 正在刷新页面同步远程数据...")
        try:
            driver.refresh()
        except:
            print("⚠️ 页面刷新超时，尝试直接读取数据...")
        
        time.sleep(3)

        # === 12. 获取续期后时间 (JS 1:1) ===
        try:
            wait.until(lambda d: re.search(r'\d+', d.find_element(By.CSS_SELECTOR, time_selector).text))
        except: pass
        after_hours_text = driver.find_element(By.CSS_SELECTOR, time_selector).text
        after_hours = int(re.sub(r'[^0-9]', '', after_hours_text)) or 0
        
        print(f"📊 判定数据: 之前 {before_hours}h -> 之后 {after_hours}h")

        # === 13. 智能逻辑判定 (JS 1:1) ===
        is_renew_success = after_hours > before_hours
        is_maxed_out = ("5 días" in error_msg) or (before_hours >= 120) or (after_hours == before_hours and after_hours >= 108)

        if is_renew_success:
            message = (f"🎉 <b>GreatHost 续期成功</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>增加时间:</b> {before_hours} ➔ {after_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {'✅ 已触发启动' if server_started else '运行正常'}\n"
                       f"📅 <b>执行时间:</b> {get_now_shanghai()}")
            send_telegram(message)
            print(" ✅ 续期成功 ✅ ")

        elif is_maxed_out:
            message = (f"✅ <b>GreatHost 已达上限</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>剩余时间:</b> {after_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {'✅ 已触发启动' if server_started else '运行正常'}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}\n"
                       f"💡 <b>提示:</b> 累计时长较高，暂无需续期。")
            send_telegram(message)
            print(" ⚠️ 已达上限/无需续期 ⚠️ ")

        else:
            message = (f"⚠️ <b>GreatHost 续期未生效</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>剩余时间:</b> {before_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {'✅ 已触发启动' if server_started else '运行中'}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}\n"
                       f"💡 <b>提示:</b> 时间未增加，请手动检查确认。")
            send_telegram(message)
            print(" 🚨 续期失败 🚨 ")

    except Exception as err:
        if "Proxy Check Failed" not in str(err):
            print(f" ❌ 运行时错误 ❌ : {err}")
            send_telegram(f"🚨 <b>GreatHost 脚本报错</b>\n<code>{err}</code>")
    finally:
        if driver:
            driver.quit()
            print("🧹 浏览器已关闭")

if __name__ == "__main__":
    run_task()
