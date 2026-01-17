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


def check_proxy_ip(driver):
    if not PROXY_URL.strip():
        print("🌍 [Check] 未设置代理，跳过预检。")
        return True
    
    proxy_dict = {"http": PROXY_URL, "https": PROXY_URL}
    now = get_now_shanghai()
    
    try:        
        resp = requests.get("https://api.ipify.org?format=json", proxies=proxy_dict, timeout=12)
        current_ip = resp.json().get('ip')      
        print(f"✅ 代理预检成功，当前 IP: {current_ip}")

        # 2. IP 段强制校验
        if not current_ip.startswith("138.68"):
            error_info = f"IP 地址({current_ip})不符合预期段(138.68)，疑似代理未生效！"
            print(f"⚠️ {error_info}")           
            
            msg = (f"🚨 <b>GreatHost IP 校验拦截</b>\n\n"
                   f"❌ <b>详情:</b> <code>{error_info}</code>\n"
                   f"📅 <b>时间:</b> {now}\n"
                   f"⚠️ <b>警告:</b> 脚本熔断")
            send_telegram(msg)
            raise Exception(error_info)

    except Exception as e:
        clean_error = str(e).replace('<', '[').replace('>', ']')
        error_info = f"代理预检或校验失败: {clean_error}"
        print(f"❌ {error_info}")
        
        # 排除掉上面手动 raise 的情况，防止重复发送 TG
        if "IP 校验拦截" not in error_info:
            msg = (f"🚨 <b>GreatHost 代理预检失败</b>\n\n"
                   f"❌ <b>详情:</b> <code>{clean_error}</code>\n"
                   f"📅 <b>时间:</b> {now}")
            send_telegram(msg)
        raise Exception(error_info)

    # 3. 浏览器层面的最终确认
    try:
        print("🌍 [Check] 正在通过浏览器确认代理响应...")
        driver.set_page_load_timeout(30)
        driver.get("https://api.ipify.org?format=json")
        return True
    except Exception as e:
        clean_error = str(e).replace('<', '[').replace('>', ']')
        error_info = f"浏览器访问代理超时: {clean_error}"
        print(f"❌ {error_info}")
        
        msg = (f"🚨 <b>GreatHost 浏览器检测超时</b>\n\n"
               f"❌ <b>详情:</b> <code>{clean_error}</code>\n"
               f"📅 <b>时间:</b> {now}")
        send_telegram(msg)
        raise Exception(error_info)    

def get_browser():
    sw_options = {'proxy': {'http': PROXY_URL, 'https': PROXY_URL, 'no_proxy': 'localhost,127.0.0.1'}}
    chrome_options = Options()  
    # 基础防封参数
    chrome_options.add_argument("--headless=new") # GitHub Actions 必须带这个，除非用 xvfb
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)    
    # 模拟真实硬件特征
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options, seleniumwire_options=sw_options)

    # 抹除核心指纹
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    
    return driver

def type_like_human(element, text):
    """模拟真人打字：随机停顿输入每个字符"""
    for char in text:
        element.send_keys(char)
        # 每个字母之间随机停顿 0.1 到 0.3 秒
        time.sleep(random.uniform(0.1, 0.3))
    
def run_task():
    # 随机延迟启动
    wait_time = random.randint(1, 300)
    print(f"⏳ 为了模拟真人，随机等待 {wait_time} 秒后启动...")
    time.sleep(wait_time)
    
    server_id = "未知"
    before_hours = 0
    after_hours = 0
    driver = None
    server_started = False
    
    try:
        driver = get_browser()        
        # === 代理熔断检查 ===
        check_proxy_ip(driver)

        # === 登录流程 (模拟真人打字版) ===
        wait = WebDriverWait(driver, 15)
        print("🔑 正在执行登录 (模拟真人输入)...")
        driver.get("https://greathost.es/login")
        
        # 1. 输入邮箱
        email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.click() # 先点击一下，模拟鼠标聚焦
        time.sleep(1)
        type_like_human(email_input, EMAIL)
        
        # 2. 输入密码
        password_input = driver.find_element(By.NAME, "password")
        password_input.click()
        time.sleep(0.5)
        type_like_human(password_input, PASSWORD)
        
        # 3. 随机发呆一秒再点登录
        time.sleep(random.uniform(1, 2))
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        
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
            status_class = status_indicator.get_attribute('class') or ''          
            print(f"📡 实时状态抓取成功: [{status_text}] (Class: {status_class})")
            
           # 判定是否需要启动
            if any(x in status_text.lower() for x in ['stopped', 'offline']):
                print(f"⚡ 检测到离线，尝试触发启动...")
                try:
                    start_btn = driver.find_element(By.CSS_SELECTOR, 'button.btn-start, .action-start')
                    # 模拟真人点击：先滚动再点
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", start_btn)
                    time.sleep(1)
                    start_btn.click()
                    server_started = True
                    print("✅ 启动指令已发出")
                except: pass
        except Exception as e:
            print(f"⚠️ 状态检查跳过: {e}")
      
        # === 3. 点击 Billing 图标 (增加随机偏移点击防止 AC 检测) ===
        print("🔍 正在定位 Billing 图标...")
        try:
            billing_btn = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, 'btn-billing-compact')))
            
            # 模拟真人：先滚动到视图中心
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", billing_btn)
            time.sleep(random.uniform(1, 2))
            
            # ⭐ 核心防封动作：随机偏移点击
            # 产生一个 -5 到 +5 像素的随机偏移量
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-5, 5)
            
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(driver)
            actions.move_to_element_with_offset(billing_btn, offset_x, offset_y).click().perform()
            
            print(f"✅ 已点击 Billing (坐标偏移: {offset_x}, {offset_y})，等待3秒...")
            time.sleep(3)
        except Exception as e:
            print(f"❌ 定位 Billing 失败，执行备用 JS 点击: {e}")
            driver.execute_script("document.querySelector('.btn-billing-compact').click();")
            time.sleep(3)

        # === 4. 点击 View Details 进入详情页 (增加稳健性) ===
        print("🔍 正在定位 View Details 链接...")
        try:
            # 等待 View Details 链接出现并可点击
            view_details_btn = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, 'View Details')))
            
            # 模拟真人：滚动到视图中心
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", view_details_btn)
            time.sleep(random.uniform(1, 3))
            
            view_details_btn.click()
            print("✅ 已进入详情页，等待3秒加载数据...")
            time.sleep(3)
        except Exception as e:
            print(f"❌ 定位 View Details 失败: {e}")
            # 备用方案：尝试通过 CSS 选择器定位（有时文本匹配会失效）
            driver.execute_script("document.querySelector('a[href*=\"details\"]').click();")
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
        digits = re.sub(r'[^0-9]', '', before_hours_text or '')
        before_hours = int(digits) if digits else 0

        # === 8. 定位按钮状态 (JS 1:1) ===
        renew_btn = driver.find_element(By.ID, 'renew-free-server-btn')
        btn_content = renew_btn.get_attribute('innerHTML')

        # === 9. 逻辑判定 (JS 1:1) ===
        print(f"🆔 ID: {server_id} | ⏰ 目前: {before_hours}h | 🔘 状态: {'冷却中' if 'Wait' in btn_content else '可续期'}")

        if 'Wait' in btn_content:
            wait_time = re.search(r'\d+', btn_content).group(0) or "??"
            
            # 直接使用全局变量 STATUS_MAP
            icon, name = STATUS_MAP.get(status_text, ["⚪", status_text])
            
            if server_started:
                status_display = f"✅ 已触发启动 ({icon} {name})"
            else:
                status_display = f"{icon} 运行正常"

            message = (f"⏳ <b>GreatHost 还在冷却中</b>\n\n"                       
                       f"🆔 <b>服务器ID:</b> <code>{server_id}</code>\n"
                       f"⏰ <b>冷却时间:</b> {wait_time} 分钟\n"
                       f"📊 <b>当前累计:</b> {before_hours}h\n"
                       f"🚀 <b>服务器状态:</b> {status_display}\n"
                       f"📅 <b>检查时间:</b> {get_now_shanghai()}")
            send_telegram(message)
            return

     # === 10. 执行续期 (模拟物理动作) ===
        print("⚡ 启动高仿真续期点击...")
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            
            # 1. 先平滑滚动，让按钮出现在屏幕中间
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", renew_btn)
            time.sleep(random.uniform(1, 2))

            # 2. 模拟鼠标平滑移动到按钮的一个随机位置点
            actions = ActionChains(driver)
            # 在按钮中心点附近随机偏离几像素，模拟人类的不精确性
            off_x = random.randint(-10, 10)
            off_y = random.randint(-5, 5)
            
            actions.move_to_element_with_offset(renew_btn, off_x, off_y)
            actions.pause(random.uniform(0.2, 0.5)) # 模拟人类点击前的短暂迟疑
            actions.click()
            actions.perform()
            
            print(f"👉 物理模拟点击成功 (偏移: {off_x}, {off_y})")
        except Exception as e:
            print(f"🚨 物理点击失败: {e}")
            # 万不得已时，在这里才考虑启用 JS 点击作为“保命”手段
            # driver.execute_script("arguments[0].click();", renew_btn)

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
        digits_after = re.sub(r'[^0-9]', '', after_hours_text or '') 
        after_hours = int(digits_after) if digits_after else 0
        
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
        if server_started:
            # 使用折返抓取的实时状态
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
        # 1. 打印原始错误日志到控制台
        print(f"❌ 运行时捕获到异常: {err}")
        
        # 2. 尝试保存当前页面源码（用于 GitHub Actions 离线分析）
        try:
            if driver:
                with open("error_page.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("💾 已保存错误页面源码至 error_page.html")
        except: pass

        # 3. 智能逻辑判定：是否需要发送业务报警通知
        # 将错误转为字符串并清洗 HTML 特殊字符，防止 TG 发送失败
        err_str = str(err).replace('<', '[').replace('>', ']')
        
        # 核心逻辑：如果报错原因不包含“代理”或“Proxy Check Failed”，
        # 说明 check_proxy_ip 已经通过，现在的报错来自于登录、点击或判定环节。
        if "Proxy Check Failed" not in err_str and "代理" not in err_str:
            now = get_now_shanghai()
            current_url = driver.current_url if driver else "未知"
            
            error_message = (f"🚨 <b>GreatHost 脚本业务报错</b>\n\n"
                             f"🆔 <b>服务器ID:</b> <code>{server_id}</code>\n"
                             f"❌ <b>错误详情:</b> <code>{err_str}</code>\n"
                             f"📍 <b>报错位置:</b> {current_url}\n"
                             f"📅 <b>发生时间:</b> {now}\n\n"
                             f"💡 <b>提示:</b> 代理连接正常，此报错可能来自登录过期或页面 UI 变动。")
            
            send_telegram(error_message)
            print("📢 已发送业务报错 TG 通知")
        else:
            print("⏭️ 检测到为代理环节报错，已由 check_proxy_ip 处理，此处跳过二次通知。")

    finally:
        # 4. 彻底清理浏览器进程
        if driver:
            try:
                driver.quit()
                print("🧹 浏览器进程已安全关闭")
            except: pass

if __name__ == "__main__":
    run_task()
