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
# 代理配置 (使用 Selenium-Wire 解决 SOCKS5 认证)
PROXY_URL = "socks5://admin123:admin321@138.68.253.225:30792"

def send_telegram(message):
    """复刻 JS: sendTelegramMessage"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=payload, timeout=10)
    except Exception as e: print(f"Telegram 发送失败: {e}")

def get_now_shanghai():
    """复刻 JS: .toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })"""
    # 简单模拟，建议根据运行环境时区调整
    return datetime.now().strftime('%Y/%m/%d %H:%M:%S')

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
    driver = None
    server_started = False
    try:
        driver = get_browser()
        wait = WebDriverWait(driver, 20)
        
        # 0. 登录流程
        print("🔑 正在执行登录...")
        driver.get("https://greathost.es/login")
        wait.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
        driver.find_element(By.NAME, "password").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        wait.until(EC.url_contains("/dashboard"))
        print("✅ 登录成功")

        # === 2. 状态检查与自动开机 (1:1 逻辑还原) ===
        print("📊 正在检查服务器实时状态...")
        try:
            status_elements = driver.find_elements(By.CSS_SELECTOR, '.status-text, .server-status')
            status_text = status_elements[0].text if status_elements else 'unknown'
        except: status_text = 'unknown'
        
        status_lower = status_text.strip().lower()

        if any(x in status_lower for x in ['offline', 'stopped', '离线']):
            print(f"⚡ 检测到离线 [{status_text}]，尝试触发启动...")
            try:
                # 使用 SVG 结构精准定位三角形启动按钮 (复刻 JS: button.btn-start[title="Start Server"])
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

        # === 3. 点击 Billing 图标进入账单页 ===
        print("🔍 点击 Billing 图标...")
        billing_btn = wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'btn-billing-compact')))
        billing_btn.click()
        print("⏳ 已进入 Billing，等待3秒...")
        time.sleep(3) # waitForTimeout(3000)

        # === 4. 点击 View Details 进入详情页 ===
        print("🔍 点击 View Details...")
        view_details = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, 'View Details')))
        view_details.click()
        print("⏳ 已进入详情页，等待3秒...")
        time.sleep(3) # waitForTimeout(3000)

        # === 5. 提前提取 ID ===
        server_id = driver.current_url.split('/')[-1] or 'unknown'
        print(f"🆔 解析到 Server ID: {server_id}")

        # === 6. 等待异步数据加载 (直到 accumulated-time 有数字且不为 0 hours) ===
        time_selector = "#accumulated-time"
        try:
            # 复刻 JS: page.waitForFunction
            wait.until(lambda d: (
                re.search(r'\d+', d.find_element(By.ID, "accumulated-time").text) and 
                d.find_element(By.ID, "accumulated-time").text.strip() != "0 hours"
            ))
        except: print("⚠️ 初始时间加载超时或为0")

        # === 7. 获取当前状态 ===
        before_hours_text = driver.find_element(By.ID, "accumulated-time").text
        before_hours = int(re.sub(r'[^0-9]', '', before_hours_text)) if re.search(r'\d+', before_hours_text) else 0

        # === 8. 定位源代码中的 ID 按钮 ===
        renew_btn = driver.find_element(By.ID, 'renew-free-server-btn')
        btn_content = renew_btn.get_attribute('innerHTML')

        # === 9. 逻辑判定 ===
        status_tag = '冷却中' if 'Wait' in btn_content else '可续期'
        print(f"🆔 ID: {server_id} | ⏰ 目前: {before_hours}h | 🔘 状态: {status_tag}")

        if 'Wait' in btn_content:
            # 9.1. 提取数字
            wait_time = re.search(r'\d+', btn_content).group(0) if re.search(r'\d+', btn_content) else "??"
            # 9.2. 组装消息 (1:1 还原 HTML 模板)
            message = (f"⏳ <b>GreatHost 还在冷却中</b>\n\n"
                       f"🆔 <b>服务器ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>剩余时间:</b> {wait_time} 分钟\n"
                       f"📊 <b>当前累计:</b> {before_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {'✅ 已触发启动' if server_started else '运行中'}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}")
            send_telegram(message)
            return

        # === 10. 执行续期 (模拟真实用户行为版) ===
        print("⚡ 启动模拟真人续期流程...")
        try:
            # 1. 模拟随机滚动
            scroll_dist = random.randint(0, 200)
            driver.execute_script(f"window.scrollBy(0, {scroll_dist});")
            print("👉 模拟页面滚动...")

            # 2. 随机发呆 2-5 秒
            time.sleep(random.uniform(2, 5))

            # 3. 模拟鼠标平滑移动
            actions = ActionChains(driver)
            # 获取按钮中心点并加随机偏差
            actions.move_to_element_with_offset(renew_btn, random.uniform(-5, 5), random.uniform(-5, 5)).perform()
            print("👉 鼠标平滑轨迹模拟完成")

            # 4. 执行“三保险”点击
            # 第一保险：物理点击 (Selenium 的 click 模拟了 mousedown/up)
            renew_btn.click()
            print("👉 [1/3] 物理点击已执行")

            # 第二保险：DOM 事件注入 (复刻 JS 的 MouseEvent 链路)
            driver.execute_script("""
                const btn = document.querySelector('#renew-free-server-btn');
                if (btn) {
                    ['mouseenter', 'mousedown', 'mouseup', 'click'].forEach(evt => {
                        btn.dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true, view: window }));
                    });
                }
            """)
            print("👉 [2/3] 事件链路注入完成")

            # 第三保险：逻辑函数直接调用 (复刻 JS 调用原生函数)
            driver.execute_script("""
                if (typeof renewFreeServer === 'function') {
                    renewFreeServer();
                }
            """)
            print("👉 [3/3] 函数触发检查完毕")
        except Exception as e:
            print(f"🚨 点击过程异常: {e}")

        # === 11. 深度等待同步 ===
        print("⏳ 正在进入 20 秒深度等待，确保后端写入数据...")
        time.sleep(20)

        # 抓取报错文本
        error_msg = ""
        try:
            error_elements = driver.find_elements(By.CSS_SELECTOR, ".toast-error, .alert-danger, .toast-message")
            error_msg = error_elements[0].text if error_elements else ""
        except: pass
        if error_msg: print(f"🔔 页面反馈信息: {error_msg}")

        # 刷新页面
        print("🔄 正在刷新页面同步远程数据...")
        driver.refresh()
        time.sleep(3)

        # === 12. 获取续期后时间 ===
        try:
            wait.until(lambda d: re.search(r'\d+', d.find_element(By.ID, "accumulated-time").text))
        except: pass
        after_hours_text = driver.find_element(By.ID, "accumulated-time").text
        after_hours = int(re.sub(r'[^0-9]', '', after_hours_text)) if re.search(r'\d+', after_hours_text) else 0
        
        print(f"📊 判定数据: 之前 {before_hours}h -> 之后 {after_hours}h")

        # === 13. 智能逻辑判定 (1:1 复刻 JS 逻辑判断矩阵) ===
        is_renew_success = after_hours > before_hours
        is_maxed_out_status = ("5 días" in error_msg) or (before_hours >= 120) or (after_hours == before_hours and after_hours >= 108)

        if is_renew_success:
            # 场景 A: 续期成功
            message = (f"🎉 <b>GreatHost 续期成功</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>增加时间:</b> {before_hours} ➔ {after_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {'✅ 已触发启动' if server_started else '运行正常'}\n"
                       f"📅 <b>执行时间:</b> {get_now_shanghai()}")
            send_telegram(message)
            print(" ✅ 续期成功 ✅ ")

        elif is_maxed_out_status:
            # 场景 B: 已达上限
            message = (f"✅ <b>GreatHost 已达上限</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>当前:</b> {after_hours}h\n"
                       f"🚀 <b>状态:</b> {'✅ 已触发启动' if server_started else '运行正常'}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}\n"
                       f"💡 <b>提示:</b> 累计时长较高，暂无需续期。")
            send_telegram(message)
            print(" ⚠️ 已达上限/无需续期 ⚠️ ")

        else:
            # 场景 C: 真正失败
            message = (f"⚠️ <b>GreatHost 续期未生效</b>\n\n"
                       f"🆔 <b>ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>当前:</b> {before_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {'✅ 已触发启动' if server_started else '运行中'}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}\n"
                       f"💡 <b>提示:</b> 时间未增加，请手动检查确认。")
            send_telegram(message)
            print(" 🚨 续期失败 🚨 ")

    except Exception as err:
        print(f" ❌ 运行时错误 ❌ : {err}")
        send_telegram(f"🚨 <b>GreatHost 脚本报错</b> 🚨\n<code>{str(err)}</code>")
    finally:
        if driver:
            driver.quit()
            print("🧹 浏览器已关闭")

if __name__ == "__main__":
    run_task()
