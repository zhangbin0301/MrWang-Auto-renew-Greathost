const EMAIL = process.env.GREATHOST_EMAIL || '';
const PASSWORD = process.env.GREATHOST_PASSWORD || '';
const CHAT_ID = process.env.CHAT_ID || '';
const BOT_TOKEN = process.env.BOT_TOKEN || '';

const { chromium } = require("playwright");
const https = require('https');

async function sendTelegramMessage(message) {
  return new Promise((resolve) => {
    const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
    const data = JSON.stringify({ chat_id: CHAT_ID, text: message, parse_mode: 'HTML' });
    const options = { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } };
    const req = https.request(url, options, (res) => {
      res.on('data', () => {});
      res.on('end', () => resolve());
    });
    req.on('error', () => resolve());
    req.write(data);
    req.end();
  });
}

(async () => {
  const GREATHOST_URL = "https://greathost.es";
  const LOGIN_URL = `${GREATHOST_URL}/login`;
  const HOME_URL = `${GREATHOST_URL}/dashboard`;

  const browser = await chromium.launch({ headless: true });
// 增加 User-Agent 伪装，让它看起来像真实的 Windows Chrome
  const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      viewport: { width: 1280, height: 720 },
      locale: 'es-ES' 
  });
  const page = await context.newPage();  

  // 抹除 Playwright 特征
    await page.addInitScript(() => {
        // 覆盖 webdriver 属性
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // 模拟插件列表
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        // 伪造 WebGL 指纹
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel(R) Iris(TM) Plus Graphics 640';
            return getParameter(parameter);
        };
    });
  // 抹除 Playwright 特征  

  try {
    // === 1. 登录 ===
    console.log("🔑 打开登录页：", LOGIN_URL);
    await page.goto(LOGIN_URL, { waitUntil: "networkidle" });
    await page.fill('input[name="email"]', EMAIL);
    await page.fill('input[name="password"]', PASSWORD);
    await Promise.all([
      page.click('button[type="submit"]'),
      page.waitForNavigation({ waitUntil: "networkidle" }),
    ]);
    console.log("✅ 登录成功！");
    await page.waitForTimeout(2000);

    
    // === 2. 状态检查与自动开机 (仅作为辅助动作) ===
    console.log("📊 正在检查服务器实时状态...");
    
    let serverStarted = false;
            // 2.1 获取当前服务器状态文字
    const statusText = (await page.locator('.status-text, .server-status').first().textContent().catch(() => 'unknown')) || 'unknown';
    const statusLower = statusText.trim().toLowerCase();

            // 2.2 执行判定与点击动作
    if (statusLower.includes('offline') || statusLower.includes('stopped') || statusLower.includes('离线')) {
        console.log(`⚡ 检测到离线 [${statusText}]，尝试触发启动...`);

        try {
                  // 使用 SVG 结构精准定位三角形启动按钮 (根据源码 button.btn-start title="Start Server")
            const startBtn = page.locator('button.btn-start[title="Start Server"]').first();
            
                  // 检查按钮是否可见，且没有 disabled 属性
            if (await startBtn.isVisible() && await startBtn.getAttribute('disabled') === null) {
                await startBtn.click();
                
                // 标记变量为 true，后面的通知会显示 "✅ 已触发启动"
                serverStarted = true; 
                
                console.log("✅ 启动指令已发出");
                // 仅等待 1 秒让请求发出去，立刻继续，不浪费时间
                await page.waitForTimeout(1000); 
            } else {
                console.log("⚠️ 启动按钮可能正在冷却或未找到，跳过启动。");
            }
        } catch (e) {
            // 这一步报错不应该影响主流程，所以 catch 里只打印日志，不抛出错误
            console.log("ℹ️ 辅助启动步骤轻微异常，忽略并继续后续续期...");
        }
    } else {
        console.log(`ℹ️ 服务器状态 [${statusText}] 正常，无需启动。`);
    }        
    
    // === 3. 点击 Billing 图标进入账单页 ===
    console.log("🔍 点击 Billing 图标...");
    const billingBtn = page.locator('.btn-billing-compact').first();
    const href = await billingBtn.getAttribute('href');
    
    await Promise.all([
      billingBtn.click(),
      page.waitForNavigation({ waitUntil: "networkidle" })
    ]);
    
    console.log("⏳ 已进入 Billing，等待3秒...");
    await page.waitForTimeout(3000);

    // === 4. 点击 View Details 进入详情页 ===
    console.log("🔍 点击 View Details...");
    await Promise.all([
      page.getByRole('link', { name: 'View Details' }).first().click(),
      page.waitForNavigation({ waitUntil: "networkidle" })
    ]);    
    console.log("⏳ 已进入详情页，等待3秒...");
    await page.waitForTimeout(3000);
    
    // === 5. 提前提取 ID，防止页面跳转后丢失上下文 ===
    const serverId = page.url().split('/').pop() || 'unknown';
    console.log(`🆔 解析到 Server ID: ${serverId}`);    

    // === 6. 等待异步数据加载 (直到 accumulated-time 有数字) ===    
    const timeSelector = '#accumulated-time';
    await page.waitForFunction(sel => {
      const el = document.querySelector(sel);
      return el && /\d+/.test(el.textContent) && el.textContent.trim() !== '0 hours';
    }, timeSelector, { timeout: 10000 }).catch(() => console.log("⚠️ 初始时间加载超时或为0"));

    // === 7. 获取当前状态 ===
    const beforeHoursText = await page.textContent(timeSelector);
    const beforeHours = parseInt(beforeHoursText.replace(/[^0-9]/g, '')) || 0;
      
    // === 8. 定位源代码中的 ID 按钮 ===
    const renewBtn = page.locator('#renew-free-server-btn');
    const btnContent = await renewBtn.innerHTML();
    
    // === 9. 逻辑判定 ===
    console.log(`🆔 ID: ${serverId} | ⏰ 目前: ${beforeHours}h | 🔘 状态: ${btnContent.includes('Wait') ? '冷却中' : '可续期'}`);
       
    if (btnContent.includes('Wait')) {
          // 9.1. 提取数字：从 "Wait 23 min" 中提取出 "23"
    const waitTime = btnContent.match(/\d+/)?.[0] || "??"; 
    
          // 9.2. 组装消息：通知用户还在冷却，并显示当前已累计的时间
    const message = `⏳ <b>GreatHost 还在冷却中</b>\n\n` +
                    `🆔 <b>服务器ID:</b> <code>${serverId}</code>\n` +
                    `⏰ <b>剩余时间:</b> ${waitTime} 分钟\n` +
                    `📊 <b>当前累计:</b> ${beforeHours}h\n` +
                    `🚀 <b>服务器状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行中'}\n` +
                    `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`;
    
    await sendTelegramMessage(message); // 发送TG通知
    await browser.close();
    return; // 结束脚本，不执行后面的点击操作
}
    
// === 10. 执行续期 (模拟真实用户行为版) ===
    console.log("⚡ 启动模拟真人续期流程...");

    try {
        // 1. 模拟真人“看页面”：随机滚动一下滚动条
        await page.mouse.wheel(0, Math.floor(Math.random() * 200));
        console.log("👉 模拟页面滚动...");
        
        // 2. 随机发呆：停顿 2-5 秒，模仿人类思考/寻找按钮的时间
        const thinkTime = Math.floor(Math.random() * 3000) + 2000;
        await page.waitForTimeout(thinkTime);

        // 3. 模拟鼠标平滑移动到按钮中心
        const box = await renewBtn.boundingBox();
        if (box) {
            // 从当前位置平滑移动到按钮
            await page.mouse.move(
                box.x + box.width / 2 + (Math.random() * 10 - 5), // 加点随机偏差
                box.y + box.height / 2 + (Math.random() * 10 - 5), 
                { steps: 15 } // 分15步移动，产生平滑轨迹
            );
            console.log("👉 鼠标平滑轨迹模拟完成");
        }

        // 4. 执行“三保险”点击
        // 第一保险：物理点击 (增加随机按键时长)
        await renewBtn.click({ 
            force: true, 
            delay: Math.floor(Math.random() * 100) + 100, // 模拟按下和弹起的间隔
            timeout: 5000 
        });
        console.log("👉 [1/3] 物理点击已执行");

        // 第二保险：DOM 事件注入 (仅在物理点击可能失效时兜底)
        await page.evaluate(() => {
            const btn = document.querySelector('#renew-free-server-btn');
            if (btn) {
                // 模拟更完整的点击链路
                ['mouseenter', 'mousedown', 'mouseup', 'click'].forEach(evt => {
                    btn.dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true, view: window }));
                });
            }
        });
        console.log("👉 [2/3] 事件链路注入完成");

        // 第三保险：逻辑函数直接调用
        await page.evaluate(() => {
            if (typeof renewFreeServer === 'function') {
                console.log("调用原生续期函数...");
                renewFreeServer();
            }
        }).catch(() => {});
        console.log("👉 [3/3] 函数触发检查完毕");

    } catch (e) {
        console.log("🚨 点击过程异常:", e.message);
    }

    // === 11. 深度等待同步 (解决 99h/108h 刷新太快读不到新数据的问题) ===
    console.log("⏳ 正在进入 20 秒深度等待，确保后端写入数据...");
    await page.waitForTimeout(20000); 

    // 抓取页面可能出现的报错文本（保留你的核心逻辑）
    const errorMsg = await page.locator('.toast-error, .alert-danger, .toast-message').textContent().catch(() => '');
    if (errorMsg) console.log(`🔔 页面反馈信息: ${errorMsg}`);

    // 刷新页面同步最新状态
    console.log("🔄 正在刷新页面同步远程数据...");
    await page.reload({ waitUntil: "domcontentloaded", timeout: 25000 })
              .catch(() => console.log("⚠️ 页面刷新超时，尝试直接读取数据..."));
    
    // 刷新后再稳 3 秒
    await page.waitForTimeout(3000);

    // === 12. 获取续期后时间 ===
    await page.waitForFunction(sel => {
        const el = document.querySelector(sel);
        return el && /\d+/.test(el.textContent);
    }, timeSelector, { timeout: 10000 }).catch(() => {});

    const afterHoursText = await page.textContent(timeSelector);
    const afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;
    
    console.log(`📊 判定数据: 之前 ${beforeHours}h -> 之后 ${afterHours}h`);

    // === 13. 智能逻辑判定 (重点修改) ===
    
    // 情况 A：时间明确增加了 -> 成功
    const isRenewSuccess = afterHours > beforeHours;

    // 情况 B：被认定为“无需续期”的满额状态
    // 满足以下任一即可：页面报5天错、之前已满120、刷新后时间处于108-120的高位
    const isMaxedOutStatus = errorMsg.includes('5 días') || 
                             beforeHours >= 120 || 
                             (afterHours === beforeHours && afterHours >= 108);

    if (isRenewSuccess) {
        // 场景 A：续期成功
        const message = `🎉 <b>GreatHost 续期成功</b>\n\n` +
                        `🆔 <b>ID:</b> <code>${serverId}</code>\n` +
                        `⏰ <b>增加时间:</b> ${beforeHours} ➔ ${afterHours}h\n` +
                        `🚀 <b>服务器状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行正常'}\n` + 
                        `📅 <b>执行时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`; 
        await sendTelegramMessage(message);
        console.log(" ✅ 续期成功 ✅ ");

    } else if (isMaxedOutStatus) {
        // 场景 B：判定为满额/接近满额
        const message = `✅ <b>GreatHost 已达上限</b>\n\n` +
                        `🆔 <b>ID:</b> <code>${serverId}</code>\n` +
                        `⏰ <b>当前:</b> ${afterHours}h\n` +
                        `🚀 <b>状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行正常'}\n` +
                        `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}\n` +      
                        `💡 <b>提示:</b> 累计时长较高，暂无需续期。`;
        await sendTelegramMessage(message);
        console.log(" ⚠️ 已达上限/无需续期 ⚠️ ");

    } else {
        // 场景 C：真正的失败（时间没到108却没增加）
        const message = `⚠️ <b>GreatHost 续期未生效</b>\n\n` +
                        `🆔 <b>ID:</b> <code>${serverId}</code>\n` +
                        `⏰ <b>当前:</b> ${beforeHours}h\n` +
                        `🚀 <b>服务器状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行中'}\n` +
                        `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}\n` +
                        `💡 <b>提示:</b> 时间未增加，请手动检查确认。`;            
        await sendTelegramMessage(message);    
        console.log(" 🚨 续期失败 🚨 ");
    }  
     } catch (err) {    
       console.error(" ❌ 运行时错误 ❌ :", err.message);
       await sendTelegramMessage(` 🚨 <b>GreatHost 脚本报错</b> 🚨 \n<code>${err.message}</code>`);
     } finally {    
       await browser.close();
     }
   })();
