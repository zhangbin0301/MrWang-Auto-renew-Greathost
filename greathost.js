const EMAIL = process.env.GREATHOST_EMAIL || '';
const PASSWORD = process.env.GREATHOST_PASSWORD || '';
const CHAT_ID = process.env.CHAT_ID || '';
const BOT_TOKEN = process.env.BOT_TOKEN || '';
  // === sock5代理配置固定IP用 (如果不需要代理，留空) ===
const PROXY_URL = (process.env.PROXY_URL || "").trim();

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

    let proxyStatusTag = "🌐 直连模式";

    // --- 修改开始：仅支持 SOCKS5 代理启动 ---
    const launchOptions = { headless: true, args: ['--no-sandbox'] };
    const proxyData = PROXY_URL ? new URL(PROXY_URL) : null;

    if (proxyData) {        
        launchOptions.proxy = { server: `socks5://${proxyData.host}` };
        proxyStatusTag = `🔒 代理模式 (${proxyData.host})`;
    }

    const browser = await chromium.launch(launchOptions);

    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport: { width: 1280, height: 720 },
        locale: 'es-ES',
        proxy: proxyData ? {
            server: `socks5://${proxyData.host}`,
            username: proxyData.username,
            password: proxyData.password
        } : undefined
    });

    const page = await context.newPage();
  
  try {
    console.log(`🚀 任务启动 | ${proxyStatusTag}`);

    // 抹除 Playwright 特征（高级伪装）
    await page.addInitScript(() => {
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en'] });
        
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel(R) Iris(TM) Plus Graphics 640';
            return getParameter(parameter);
        };
    });

    console.log(`✅ 环境初始化完成 | ${proxyStatusTag}`);
  
    // --- 新增：代理 IP 检查与熔断机制 ---
    if (PROXY_URL) {
      console.log("🌍 [Check] 正在检测代理 IP...");
      try {
        await page.goto("https://api.ipify.org?format=json", { timeout: 20000 });
        const ipInfo = JSON.parse(await page.innerText('body'));
        console.log(`✅ 当前出口 IP: ${ipInfo.ip}`);        
        
        if (!ipInfo.ip.startsWith("138.68")) {
            console.log(`⚠️ 警告: IP (${ipInfo.ip}) 似乎不是预期的代理 IP！`);
        }
      } catch (e) {
        const errorMsg = `❌ 代理检查失败: ${e.message}`;
        console.error(errorMsg);
        await sendTelegramMessage(`🚨 <b>GreatHost 代理异常</b>\n模式: ${proxyStatusTag}\n原因: ${e.message}`);
        throw new Error("Proxy Check Failed - 脚本停止以防止直连"); 
      }
    } 

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

    // 定义通用报告函数
    const getReport = (icon, title, hours, detail) => {
        return `${icon} <b>GreatHost ${title}</b>\n\n` +
               `🆔 <b>服务器ID:</b> <code>${serverId}</code>\n` +
               `⏰ <b>${title.includes('冷却') ? '累计时长' : '最新时长'}:</b> ${hours}h\n` +
               `🚀 <b>运行状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行正常'}\n` +
               `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}\n` +
               `💡 <b>判定说明:</b> ${detail}`;
    };

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
        await sendTelegramMessage(getReport('⏳', '还在冷却中', beforeHours, `处于冷却中，剩 ${waitTime} 分钟`));
        return; 
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

// === 12. 获取续期后时间 (增强容错版) ===
    let afterHours = 0;
    try {
        console.log("⏳ 正在等待数据渲染...");
        
        await page.waitForFunction((sel, pre) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            const current = parseInt(el.textContent.replace(/[^0-9]/g, ''));
            return !isNaN(current) && (current > 0 || current !== pre);
        }, timeSelector, beforeHours, { timeout: 15000 });

        const afterHoursText = await page.textContent(timeSelector);
        afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;

        if (afterHours === 0 && beforeHours > 0) {
            console.log("⚠️ 检测到异常 0h，尝试二次重读...");
            await page.waitForTimeout(3000);
            const retryText = await page.textContent(timeSelector);
            afterHours = parseInt(retryText.replace(/[^0-9]/g, '')) || 0;
        }
    } catch (e) {
        console.log("⚠️ 数据同步超时，将使用刷新前的时间进行判定。");
        afterHours = beforeHours; 
    }

    if (afterHours === 0 && beforeHours > 0) {
        afterHours = beforeHours;
    }
    
    console.log(`📊 判定数据: 之前 ${beforeHours}h -> 之后 ${afterHours}h`);

    // === 13. 智能逻辑判定 ===        
    let statusIcon = '🚨';
    let statusTitle = '续期结果待核实';
    let tip = '';

    if (afterHours > beforeHours) {
        statusIcon = '🎉';
        statusTitle = '续期成功';
        tip = `时长已从 ${beforeHours}h 成功增加至 ${afterHours}h。`;
    } 
    else if (
        (typeof errorMsg !== 'undefined' && errorMsg.includes('5 días')) || 
        beforeHours >= 120 || 
        (afterHours === beforeHours && afterHours >= 108)
    ) {
        statusIcon = '✅';
        statusTitle = '暂无需续期';
        tip = afterHours >= 108 
            ? `当前时长 ${afterHours}h 已接近 120h 上限，系统保护中。` 
            : `服务器反馈：已达 5 天续期上限。`;
    }
    else if (afterHours === beforeHours) {
        statusIcon = '⏳'; 
        statusTitle = '时长未刷新';
        tip = `点击了续期但时长仍为 ${afterHours}h。可能是后端延迟，请稍后在网页端检查。`;
    }
    else {
        statusIcon = '❌';
        statusTitle = '数据异常';
        tip = `检测到时长离奇变动：从 ${beforeHours}h 变为 ${afterHours}h。建议人工检查。`;
    }

    // === 14. 发送正常消息 ===
    await sendTelegramMessage(getReport(statusIcon, statusTitle, afterHours, tip));   

  } catch (err) {
    console.error("❌ 脚本运行崩溃:", err.message);

    // 如果报错是因为“代理检查失败”，说明前面已经发过 TG 了，这里就不重复发了
    if (!err.message.includes("Proxy Check Failed")) {
        const errorDetail = 
            `🚨 <b>GreatHost 脚本崩溃</b>\n\n` +
            `🌐 <b>连接模式:</b> ${proxyStatusTag}\n` +
            `❌ <b>错误信息:</b> <code>${err.message}</code>\n` +
            `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`;
        
        await sendTelegramMessage(errorDetail);        
    }   

  } finally {
    
    if (typeof browser !== 'undefined' && browser) {
        try {
            console.log("🧹 [Exit] 正在关闭浏览器...");
            await browser.close();
        } catch (closeErr) {
            console.error("⚠️ 关闭浏览器时发生异常:", closeErr.message);
        }
    }
  }
})();
