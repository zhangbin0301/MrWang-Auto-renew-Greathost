import os
import re
import time
import json
import requests
from datetime import datetime, timezone
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
TARGET_NAME_CONFIG = os.getenv("TARGET_NAME", "loveMC")
TARGET_SERVER_ID = os.getenv("TARGET_SERVER_ID", "")

# 可调参数
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
FETCH_RETRY = int(os.getenv("FETCH_RETRY", "8"))
FETCH_WAIT = float(os.getenv("FETCH_WAIT", "1.0"))

# 状态映射表
STATUS_MAP = {
    "Running": ["🟢", "Running"],
    "Starting": ["🟡", "Starting"],
    "Stopped": ["🔴", "Stopped"],
    "Offline": ["⚪", "Offline"],
    "Suspended": ["🚫", "Suspended"]
}

# ================= 小工具 =================
def dprint(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

def now_shanghai():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime('%Y/%m/%d %H:%M:%S')

def calculate_hours(date_str):
    """解析 ISO 时间换算为剩余小时数；解析失败返回 None"""
    try:
        if not date_str:
            return None
        clean_date = re.sub(r'\.\d+Z$', 'Z', str(date_str))
        expiry = datetime.fromisoformat(clean_date.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = (expiry - now).total_seconds() / 3600
        return max(0, int(diff))
    except Exception:
        return None

def is_json_dict(obj):
    """
    判断对象是否为有效的业务 JSON dict（可安全读取 contract/servers 等字段）。
    返回 True 表示可以直接使用 obj.get(...)
    """
    if not isinstance(obj, dict):
        return False
    if obj.get("__raw_text") is not None:
        return False
    if obj.get("success") is False:
        return False
    if "contract" in obj or "servers" in obj or "message" in obj or "status" in obj:
        return True
    return len(obj) > 0

# ================= 浏览器内 fetch 封装 =================
def fetch_api(driver, url, method="GET"):
    """
    在浏览器上下文执行 fetch，显式 Accept 为 JSON；若无法解析 JSON，返回包含 __raw_text 的 dict。
    注意：url 可以是相对路径（如 /api/servers），在浏览器上下文会以当前域名发起请求。
    """
    script = f"""
    return fetch('{url}', {{
        method: '{method}',
        headers: {{ 'Accept': 'application/json, text/plain, */*' }}
    }})
    .then(async r => {{
        const ct = r.headers.get('content-type') || '';
        const text = await r.text();
        try {{
            return JSON.parse(text);
        }} catch(e) {{
            return {{success:false, __raw_text: text, __content_type: ct, __status: r.status}};
        }}
    }})
    .catch(e => ({{success:false, message: e.toString()}}))
    """
    return driver.execute_script(script)

def extract_json_from_requests(driver, server_id, lookback=200):
    """
    从 seleniumwire 的请求日志倒序查找与 server_id 相关的最近 JSON 响应。
    返回解析后的 dict 或 None。
    同时会在 DEBUG 模式下打印候选请求信息，便于对照 F12 Network。
    """
    for req in reversed(driver.requests[-lookback:]):
        if server_id in (req.url or ""):
            status = req.response.status_code if req.response else None
            ct = req.response.headers.get('Content-Type','') if req.response else ''
            try:
                body = req.response.body.decode('utf-8', errors='replace') if req.response else ''
            except Exception:
                body = ''
            dprint("DEBUG candidate:", req.method, req.url, status, ct, "body_len=", len(body))
            # 优先 content-type 为 json
            if ct and 'application/json' in ct.lower():
                try:
                    parsed = json.loads(body)
                    dprint("DEBUG selected JSON request:", req.method, req.url, status, ct)
                    return parsed
                except Exception:
                    return {"success": False, "__raw_text": body, "__content_type": ct, "__status": status}
            # 其次 body 以 { 开头也可能是 JSON
            if body.strip().startswith('{'):
                try:
                    parsed = json.loads(body)
                    dprint("DEBUG selected JSON by body:", req.method, req.url, status, ct)
                    return parsed
                except Exception:
                    return {"success": False, "__raw_text": body, "__content_type": ct, "__status": status}
    return None

# ================= 通知系统 =================
def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        dprint("TG not configured, skip send")
        return
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
    serverName = "未知名称"
    try:
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
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

        # 2. 获取 ID 并同时抓取 name（优先使用 TARGET_SERVER_ID）
        res = fetch_api(driver, "/api/servers")
        dprint("DEBUG /api/servers raw:", res if DEBUG else "hidden")
        if not is_json_dict(res) or "servers" not in res:
            raise Exception("/api/servers 未返回有效 JSON，请检查会话或接口")

        server_list = res.get("servers") or []

        if TARGET_SERVER_ID:
            target_server = next((s for s in server_list if s.get('id') == TARGET_SERVER_ID), None)
            if not target_server:
                raise Exception(f"未找到指定的 server_id: {TARGET_SERVER_ID}")
        else:
            matches = [s for s in server_list if s.get('name') == TARGET_NAME_CONFIG]
            if not matches:
                raise Exception(f"未找到服务器: {TARGET_NAME_CONFIG}")
            if len(matches) == 1:
                target_server = matches[0]
            else:
                dprint("DEBUG 找到多个同名服务器，候选列表：", json.dumps(matches, indent=2, ensure_ascii=False))
                def _parse_created(s):
                    try:
                        return s.get('createdAt') or ""
                    except:
                        return ""
                matches_sorted = sorted(matches, key=_parse_created, reverse=True)
                target_server = matches_sorted[0]
                dprint("DEBUG 已自动选择最新创建的同名服务器：", json.dumps(target_server, indent=2, ensure_ascii=False))

        server_id = target_server.get('id')
        serverName = target_server.get('name') or serverName
        dprint("DEBUG 选中服务器：name =", serverName, "id =", server_id, "createdAt =", target_server.get('createdAt'))

        # 3. 抓取 status (information 页面)
        driver.get(f"https://greathost.es/server-information-free.html?id={server_id}")
        time.sleep(5)
        info_res = fetch_api(driver, f"/api/servers/{server_id}/information")
        if not is_json_dict(info_res):
            dprint("WARN: information 接口返回异常:", info_res)
        raw_status = info_res.get('status', 'Unknown') if isinstance(info_res, dict) else 'Unknown'
        status_info = STATUS_MAP.get(raw_status.capitalize(), ["❓", raw_status])
        status_display = f"{status_info[0]} {status_info[1]}"

        # 4. 抓取续期前时间 (contract 页面) —— 优先取 JSON XHR，回退到请求日志
        driver.get(f"https://greathost.es/contracts/{server_id}")
        time.sleep(2)  # 让页面开始触发 XHR

        contract_res = fetch_api(driver, f"/api/servers/{server_id}/contract")
        try:
            dprint("DEBUG /contract raw:", json.dumps(contract_res, indent=2, ensure_ascii=False))
        except Exception:
            dprint("DEBUG /contract raw (non-serializable):", type(contract_res), str(contract_res)[:1000])

        # 如果 fetch_api 返回原始文本（HTML），尝试从 seleniumwire 请求日志中提取最近的 JSON 响应
        if not is_json_dict(contract_res):
            dprint("DEBUG /contract fetch 未返回有效 JSON，尝试从请求日志中查找 JSON 响应...")
            found = extract_json_from_requests(driver, server_id)
            if found and is_json_dict(found):
                contract_res = found
            else:
                # 页面 JS 可能稍后才发 XHR，短轮询几次再试
                for _ in range(FETCH_RETRY):
                    time.sleep(FETCH_WAIT)
                    found = extract_json_from_requests(driver, server_id)
                    if found and is_json_dict(found):
                        contract_res = found
                        break

        # 如果仍然没有 JSON，做一次页面重载并重试（最后手段）
        if not is_json_dict(contract_res):
            dprint("DEBUG /contract 仍未拿到 JSON，尝试重新加载页面并重试一次...")
            driver.get(f"https://greathost.es/contracts/{server_id}")
            time.sleep(3)
            contract_res = fetch_api(driver, f"/api/servers/{server_id}/contract")
            if not is_json_dict(contract_res):
                dprint("DEBUG /contract retry raw (non-serializable):", type(contract_res), str(contract_res)[:1000])
                # 打印最近相关请求以便排查，然后抛出异常
                dprint("DEBUG contract 接口重试仍返回非 JSON，开始打印相关请求（最多 30 条）以便排查：")
                for req in driver.requests[-30:]:
                    if server_id in (req.url or "") or "/api/servers" in (req.url or ""):
                        dprint(req.method, req.url, req.response.status_code if req.response else None)
                        if req.response:
                            try:
                                dprint(req.response.body.decode('utf-8', errors='replace')[:2000])
                            except Exception:
                                dprint("DEBUG 无法解码响应体")
                raise Exception("contract 接口未返回有效 JSON（重试失败），可能会话失效或被拦截")

        # 解析 contract_res（兼容不同返回结构）
        c_data = {}
        if isinstance(contract_res, dict):
            c_data = contract_res.get('contract') or {}
            if not isinstance(c_data, dict):
                c_data = {}

        r_info = c_data.get('renewalInfo', {}) if isinstance(c_data, dict) else {}

        # 优先使用 contract 返回的 serverName（若存在），否则保留之前的 target_server name
        serverName = c_data.get("serverName") or serverName

        next_dt = r_info.get('nextRenewalDate')
        before_h = calculate_hours(next_dt)
        last_renew_str = r_info.get('lastRenewalDate')

        dprint("DEBUG serverName =", serverName)
        dprint("DEBUG nextRenewalDate =", next_dt)
        dprint("DEBUG lastRenewalDate =", last_renew_str)
        dprint("DEBUG before_h =", before_h)

        # --- 冷却判定逻辑 (保持 30 分钟冷却) ---
        if last_renew_str:
            clean_last = re.sub(r'\.\d+Z$', 'Z', str(last_renew_str))
            try:
                last_time = datetime.fromisoformat(clean_last.replace('Z', '+00:00'))
            except Exception as e:
                dprint("DEBUG 解析 last_renew_str 失败:", clean_last, "错误:", e)
                last_time = None

            now_time = datetime.now(timezone.utc)
            minutes_passed = None
            if last_time:
                minutes_passed = (now_time - last_time).total_seconds() / 60

            dprint("DEBUG 冷却检查原始 last_renew_str =", last_renew_str)
            dprint("DEBUG clean_last =", clean_last)
            dprint("DEBUG last_time (UTC) =", last_time)
            dprint("DEBUG now_time (UTC) =", now_time)
            dprint("DEBUG minutes_passed =", minutes_passed)

            if minutes_passed is not None and minutes_passed < 30:
                wait_min = int(30 - minutes_passed)
                dprint("DEBUG 处于冷却期，剩余分钟 =", wait_min)
                fields = [("📛","服务器名称", serverName),("🆔","ID",f"<code>{server_id}</code>"),("⏰","冷却倒计时",f"{wait_min} 分钟"),("📊","当前累计",f"{before_h if before_h is not None else '未知'}h"),("🚀","状态",status_display)]
                send_notice("cooldown", fields)
                return
            else:
                dprint("DEBUG 不在冷却期，minutes_passed =", minutes_passed)

        # 5. 执行续期 POST
        print(f"🚀 正在为 {serverName} 发送续期请求...")
        renew_res = fetch_api(driver, f"/api/renewal/contracts/{server_id}/renew-free", method="POST")
        try:
            dprint("DEBUG renew_res:", json.dumps(renew_res, indent=2, ensure_ascii=False))
        except Exception:
            dprint("DEBUG renew_res (non-serializable):", type(renew_res), str(renew_res)[:1000])

        # 6. 循环等待后台写入 nextRenewalDate（最多等 15 秒）
        after_h = 0
        for _ in range(5):
            time.sleep(3)
            renew_contract = fetch_api(driver, f"/api/servers/{server_id}/contract")
            # 若返回非 JSON，尝试从请求日志中提取
            if not is_json_dict(renew_contract):
                found = extract_json_from_requests(driver, server_id)
                if found and is_json_dict(found):
                    renew_contract = found

            try:
                dprint("DEBUG loop raw:", json.dumps(renew_contract, ensure_ascii=False))
            except Exception:
                dprint("DEBUG loop raw (non-serializable):", type(renew_contract), str(renew_contract)[:500])

            renew_c = {}
            if isinstance(renew_contract, dict):
                renew_c = renew_contract.get('contract') or renew_contract
                if not isinstance(renew_c, dict):
                    renew_c = {}

            try:
                dprint("DEBUG loop contract:", json.dumps(renew_c, ensure_ascii=False))
            except Exception:
                dprint("DEBUG loop contract (non-serializable):", type(renew_c))

            next_dt_loop = renew_c.get('renewalInfo', {}).get('nextRenewalDate') if isinstance(renew_c, dict) else None
            after_h = calculate_hours(next_dt_loop) or 0

            dprint("DEBUG 循环检查 after_h =", after_h, " nextRenewalDate =", next_dt_loop)
            if after_h > (before_h or 0):
                break

        # 7. 判定与通知
        is_success = after_h > (before_h or 0)
        dprint("DEBUG 判定：before_h =", before_h, "after_h =", after_h, "is_success =", is_success)
        msg_str = str(renew_res.get('message', '')).lower() if isinstance(renew_res, dict) else ""
        has_limit_msg = "5 días" in msg_str or "no puedes renovar" in msg_str or "limit" in msg_str

        is_near_max = (before_h or 0) >= 120 or after_h >= 120 or ((before_h or 0) >= 108 and after_h <= (before_h or 0))
        is_maxed = is_near_max or (has_limit_msg and renew_res.get('success'))

        if is_success:
            fields = [
                ("📛","服务器名称", serverName),
                ("🆔","ID", f"<code>{server_id}</code>"),
                ("⏰","增加时间", f"{before_h if before_h is not None else '未知'} ➔ {after_h}h"),
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
                ("⏰","剩余时间", f"{before_h if before_h is not None else '未知'}h"),
                ("🚀","服务器状态", status_display),
                ("💡","提示", "时间未增加，请手动确认。")
            ]
            send_notice("renew_failed", fields)

    except Exception as e:
        err = str(e).replace('<','[').replace('>',']')
        print("Runtime error:", err)
        send_notice("business_error", [("📛","服务器名称", serverName),("🆔","ID",f"<code>{server_id}</code>"),("❌","详情",f"<code>{err}</code>")])
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    run_task()
