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
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

# ================= 环境变量获取 =================
EMAIL = os.getenv("GREATHOST_EMAIL") or ""
PASSWORD = os.getenv("GREATHOST_PASSWORD") or ""
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or ""
# sock5代码，不需要留空值 64行左右要填上IP头
PROXY_URL = os.getenv("PROXY_URL") or ""

def send_telegram(msg_text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    # 核心修改：强制 TG 发送不走代理，防止代理挂了导致通知也挂了
    session = requests.Session()
    session.trust_env = False 
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg_text, "parse_mode": "HTML"}
        # 设置较短的 timeout，防止卡死
        session.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Telegram 发送最终失败: {e}")

STATUS_MAP = {
    "Running":   ["🟢", "运行中"],
    "Starting":  ["🟡", "启动中"],
    "Stopped":   ["🔴", "已关机"],
    "Offline":   ["⚪", "离线"],
    "Suspended": ["🚫", "已暂停/封禁"]
}

def get_now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

# === 统一封装步骤===
def perform_step(driver, wait, desc, locator, js_selector=None):
        try:
                print(f"🔍 正在定位 {desc} ...")
                element = wait.until(EC.element_to_be_clickable(locator))

                click_button(driver, element, desc, js_selector)

        except Exception as e:
                print(f"⚠️ {desc} 执行失败: {e}")


# 通用按钮点击逻辑：- 滚动到中央- 随机等待- safe_click- JS 强制点击兜底- 等待3秒       
def click_button(driver, element, desc, js_selector=None):        
        try:
                # 滚动到视图中央
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                # 随机等待
                delay = random.uniform(1.0, 3.0)
                print(f"⏳ {desc} 点击前随机等待 {delay:.2f} 秒...")
                time.sleep(delay)
            
                # safe_click（主力点击）
                safe_click(driver, element)
                print(f"✅ safe_click 成功触发 {desc}")
                return True
            
        except Exception as e:
                print(f"⚠️ safe_click 触发 {desc} 失败，尝试 JS 兜底: {e}")
                # JS 兜底
                try:
                        if js_selector:
                                driver.execute_script(f"document.querySelector('{js_selector}').click();")
                        else:
                                driver.execute_script("arguments[0].click();", element)
                        print(f"⚡ JS 强制点击 {desc} 成功")
                        return True

                except Exception as e2:
                        print(f"🚨 JS 强制点击 {desc} 也失败: {e2}")
                        return False
        # 点击后等待 3 秒（统一行为）
        time.sleep(3)
        return True
    
def mask_host(host):
    if not host:
        return "Unknown"
        
    # --- 处理 IPv6 ---
    if ":" in host:
        parts = host.split(':')
        if len(parts) > 3:
            # 保留前两段和最后一段
            return f"{parts[0]}:{parts[1]}:****:{parts[-1]}"
        return f"{host[:9]}****"    
    # --- 处理 IPv4 ---
    parts = host.split('.')
    if len(parts) == 4:
        # 格式：第一段.第二段.***.第四段
        return f"{parts[0]}.{parts[1]}.***.{parts[3]}"    
    # --- 处理域名或其他 ---
    if len(parts) >= 3:
        return f"{parts[0]}.****.{parts[-1]}"    
        
    return f"{host[:4]}****"
    
def get_proxy_expected_host():    
    raw_proxy = (os.getenv("PROXY_URL") or "").strip()
    if not raw_proxy: return None   
    try:
        # 兼容处理不带协议头的字符串
        temp_url = raw_proxy if "://" in raw_proxy else f"http://{raw_proxy}"
        host = urlparse(temp_url).hostname
        return host.lower().replace("[", "").replace("]", "") if host else None
    except: return None

EXPECTED_HOST = get_proxy_expected_host()

def check_proxy_ip(driver):
    if not PROXY_URL.strip():
        print("🌍 [Check] 未设置代理，跳过预检。")
        return True
    
    proxy_dict = {"http": PROXY_URL, "https": PROXY_URL}
    now = get_now_shanghai()
    
    try:      
        # 1. 尝试连接 (死掉检查)
        resp = requests.get("https://api64.ipify.org?format=json", proxies=proxy_dict, timeout=12)
        current_ip = resp.json().get('ip').lower()      
        print(f"✅ 代理预检成功，当前 IP: {current_ip}")

        # 2. 安全比对 (叛变检查)
        is_safe = True
        if EXPECTED_HOST:           
            match_full = (EXPECTED_HOST in current_ip) or (current_ip in PROXY_URL.lower())
            ipv6_prefix_match = (":" in current_ip and ":" in EXPECTED_HOST and 
                                 current_ip.split(':')[:4] == EXPECTED_HOST.split(':')[:4])
            if not (match_full or ipv6_prefix_match):
                is_safe = False

        if not is_safe:
            # 抛出带标识的异常，交给下方 except 统一处理
            m_exp, m_cur = mask_host(EXPECTED_HOST), mask_host(current_ip)
            raise Exception(f"BLOCK_ERR|{m_exp}|{m_cur}")

        # 3. 浏览器确认 (忠诚检查最后一步)
        driver.set_page_load_timeout(30)
        driver.get("https://api.ipify.org?format=json")
        return True

    except Exception as e:
        clean_error = str(e).replace('<', '[').replace('>', ']')
        
        # --- 统一出口逻辑 ---
        if "BLOCK_ERR" in clean_error:
            # 叛变拦截：IP 不匹配
            _, m_exp, m_cur = clean_error.split('|')
            msg = (f"🚨 <b>GreatHost IP 校验拦截</b>\n\n"
                   f"❌ <b>配置代理:</b> <code>{m_exp}</code>\n"
                   f"❌ <b>实际出口:</b> <code>{m_cur}</code>\n"
                   f"⚠️ <b>警告:</b> 代理已偏离，脚本熔断")
        else:
            # 死掉/超时：连接不通
            msg = (f"🚨 <b>GreatHost 代理预检失败</b>\n\n"
                   f"❌ <b>详情:</b> <code>{clean_error}</code>\n"
                   f"⚠️ <b>结果:</b> 连接超时或服务不可用")

        msg += f"\n📅 <b>时间:</b> {now}"
        print(f"❌ {msg.split('<b>')[1].split('</b>')[0]}: {clean_error}")
        send_telegram(msg)
        raise Exception(clean_error)

def get_browser():
    sw_options = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL, 'no_proxy': 'localhost,127.0.0.1'}}
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options, seleniumwire_options=sw_options)
    return driver

def safe_send_keys(element, text):    
    try:
        element.clear()
    except Exception:
        pass
    element.send_keys(text)
    time.sleep(0.13)

def safe_click(driver, element):
    try:
        element.click()
    except Exception as e:
        print("⚠️ 普通点击失败，尝试 JS 兜底:", e)
        try:
            driver.execute_script("arguments[0].click();", element)
        except Exception as ex:
            print("❌ JS 点击也失败:", ex)
            raise
    
def run_task():
    # 随机延迟启动
    wait_time = random.randint(1, 100)
    print(f"⏳ 模拟真人，随机等待 {wait_time} 秒后启动...")
    time.sleep(wait_time)

    driver = None
    server_id = "未知"
    before_hours = 0
    after_hours = 0
    server_started = False
    status_text = "Unknown"
    status_display = "🟢 运行正常"
    get_hours = lambda text: int(re.sub(r'[^0-9]', '', text or '0')) if re.search(r'\d+', text or '') else 0
    
    try:
        driver = get_browser()        
        # === 代理熔断检查 ===
        check_proxy_ip(driver)

        # === 登录流程 (模拟真人打字版) ===
        wait = WebDriverWait(driver, 15)
        print("🔑 正在执行登录 (模拟人输入)...")
        driver.get("https://greathost.es/login")
        
        # 1. 输入邮箱
        email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        try:
            safe_click(driver, email_input)  # 聚焦
        except Exception:
            pass
        time.sleep(0.3)
        safe_send_keys(email_input, EMAIL)

        # 2. 输入密码
        password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
        try:
            safe_click(driver, password_input)
        except Exception:
            pass
        time.sleep(0.4)
        safe_send_keys(password_input, PASSWORD)

        # 3. 短暂等待后点击登录（保留原意的短暂停顿）
        time.sleep(random.uniform(0.8, 1.6))
        submit_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']")))
        safe_click(driver, submit_btn)        
        
        wait.until(EC.url_contains("/dashboard"))
        print("✅ 登录成功！")

         # 登录成功后，不要立刻去点 Billing
        print("🎲 执行随机假动作...")
        if random.random() > 0.5:
            driver.get("https://greathost.es/services") # 先去服务列表晃一圈
            time.sleep(random.randint(4, 8))
            # 2. 回到 Dashboard (或者直接跳回 Dashboard)
            print("🏠 正在返回仪表盘...")
            driver.get("https://greathost.es/dashboard") 
            wait.until(EC.url_contains("/dashboard"))
            time.sleep(random.uniform(1, 4))

     # === 2. 状态检查与自动开机 (针对新版小圆点 UI 优化) ===
        print("📊 正在检查服务器实时状态...")
        try:
                status_indicator = wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'server-status-indicator')))
                status_text = status_indicator.get_attribute('title') or 'unknown'

                if any(x in status_text.lower() for x in ['stopped', 'offline']):
                        print("⚡ 检测到服务器离线，准备执行启动...")

                        perform_step(      
                                driver,
                                wait,
                                "启动按钮",
                                (By.CSS_SELECTOR, 'button.btn-start, .action-start'),     
                                "button.btn-start, .action-start"
                        )
                        server_started = True

      # === 3. 点击 Billing 图标（统一封装步骤）===
        perform_step(
                driver,
                wait,
                "Billing 图标",
                (By.CLASS_NAME, 'btn-billing-compact'),
                ".btn-billing-compact"
         )   
                
        # === 4. 点击 View Details（统一封装步骤）===
        perform_step(
                driver,
                wait,
                "View Details",
                (By.LINK_TEXT, 'View Details'),
                "a[href*='details']"
         )   

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
        before_hours = get_hours(before_hours_text)

        # === 8. 定位按钮状态 (JS 1:1) ===
        renew_btn = wait.until(EC.presence_of_element_located((By.ID, "renew-free-server-btn")))
        btn_content = renew_btn.get_attribute('innerHTML')

        # === 9. 逻辑判定 (JS 1:1) ===
        print(f"🆔 ID: {server_id} | ⏰ 目前: {before_hours}h | 🔘 状态: {'冷却中' if 'Wait' in btn_content else '可续期'}")

        if 'Wait' in btn_content:
            m = re.search(r'\d+', btn_content)
            wait_time = m.group(0) if m else "??"
            
            message = (f"⏳ <b>GreatHost 还在冷却中</b>\n\n"                       
                       f"🆔 <b>服务器ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>冷却时间:</b> {wait_time} 分钟\n"
                       f"📊 <b>当前累计:</b> {before_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {status_display}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}")
            print("ℹ️ 发送冷却通知:", message)
            send_telegram(message)
            try:
                if driver:
                    driver.quit()
            except: pass        
            return

       # === 10. 执行续期（统一封装步骤）===
        perform_step(
                driver,
                wait,
                "续期按钮",
                (By.ID, 'renew-free-server-btn')                
         )   

        # 深度等待，确保后端写入
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
        after_hours = get_hours(after_hours_text)
        
        print(f"📊 判定数据: 之前 {before_hours}h -> 之后 {after_hours}h")


        # === 13.  [新增] 仅在触发启动后，折返确认最终状态 ===
        final_status_text = "运行正常" # 默认文案
        if server_started:
            print("🔄 检测到曾触发启动动作，正在折返 Dashboard 确认最终状态...")
            try:
                driver.get("https://greathost.es/dashboard")
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'server-status-indicator')))
                time.sleep(2) # 稍作等待
                
                # 重新抓取圆点的 title
                final_indicator = driver.find_element(By.CLASS_NAME, 'server-status-indicator')
                final_status_text = final_indicator.get_attribute('title') or "Unknown"
                print(f"📡 最终状态确认: [{final_status_text}]")
                
                # 抓取完后，为了不影响后续逻辑，跳回续期页面或保持在此
                # 既然已经判定完 after_hours，留在 Dashboard 也是安全的
            except Exception as e:
                print(f"⚠️ 最终状态同步失败: {e}")
                final_status_text = "确认失败"

        # === 14. 智能逻辑判定 (JS 1:1) ===
        is_renew_success = after_hours > before_hours
        is_maxed_out = ("5 días" in error_msg) or (before_hours >= 120) or (after_hours == before_hours and after_hours >= 108)

        # 🚀 统一构造服务器状态显示文案 (使用全局 STATUS_MAP)
        if server_started and 'final_status_text' in locals():
            icon, name = STATUS_MAP.get(final_status_text, ["❓", final_status_text])
            status_display = f"✅ 已触发启动 ({icon} {name})"
        else:
            # 未启动过则显示初始状态或默认正常
            icon, name = STATUS_MAP.get(status_text, ["🟢", "运行正常"])
            status_display = f"{icon} {name}"

        # === 15. 分发最终通知 ===
        if is_renew_success:
            message = (f"🎉 <b>GreatHost 续期成功</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>增加时间:</b> {before_hours} ➔ {after_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {status_display}\n"
                       f"📅 <b>执行时间:</b> {get_now_shanghai()}")
            send_telegram(message)
            print(" ✅ 续期成功 ✅ ")

        elif is_maxed_out:
            message = (f"✅ <b>GreatHost 已达上限</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>剩余时间:</b> {after_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {status_display}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}\n"
                       f"💡 <b>提示:</b> 累计时长较高，暂无需续期。")
            send_telegram(message)
            print(" ⚠️ 已达上限/无需续期 ⚠️ ")

        else:
            message = (f"⚠️ <b>GreatHost 续期未生效</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>剩余时间:</b> {before_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {status_display}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}\n"
                       f"💡 <b>提示:</b> 时间未增加，请手动检查确认。")
            send_telegram(message)
            print(" 🚨 续期失败 🚨 ")

    except Exception as err:
        err_str = str(err).replace('<', '[').replace('>', ']')
        print(f"❌ 运行时捕获到异常: {err_str}")
        
        # 存证
        if driver:
            try:
                driver.save_screenshot("error.png")
                with open("error_page.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except: pass

        # 智能判定：只在非代理错误时发送“业务报错”
        # 因为代理错误在 check_proxy_ip 里已经发过 TG 并 raise 了
        if "BLOCK_ERR" not in err_str and "代理预检" not in err_str:
            now = get_now_shanghai()
            current_url = driver.current_url if driver else "未知"
            error_message = (f"🚨 <b>GreatHost 脚本业务报错</b>\n\n"
                             f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                             f"❌ <b>详情:</b> <code>{err_str}</code>\n"
                             f"📍 <b>位置:</b> {current_url}\n"
                             f"📅 <b>时间:</b> {now}")
            send_telegram(error_message)
            print("📢 业务报错已发送通知")
        else:
            print("⏭️ 代理链路拦截，跳过业务二次通知。")

    finally:
        # 4. 彻底清理浏览器进程
        if driver:
            try:
                driver.quit()
                print("🧹 浏览器进程已安全关闭")
            except: pass

if __name__ == "__main__":
    run_task()
