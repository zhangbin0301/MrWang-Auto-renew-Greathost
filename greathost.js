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
  const page = await browser.newPage();

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

    // 放在 try 块的这个位置是安全的，只要不放在 if 里面即可
    let serverStarted = false;

    // 1. 获取当前状态文字
    const statusText = await page.locator('.status-text, .server-status').first().textContent().catch(() => 'unknown');
    const statusLower = statusText.trim().toLowerCase();

    // 2. 执行判定与点击动作
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
                console.log("⚠️ 启动按钮不可用(可能正在冷却或未找到)，跳过启动。");
            }
        } catch (e) {
            // 这一步报错不应该影响主流程，所以 catch 里只打印日志，不抛出错误
            console.log("ℹ️ 辅助启动步骤轻微异常，忽略并继续后续续期...");
        }
    } else {
        console.log(`ℹ️ 服务器状态 [${statusText}] 正常，无需启动。`);
    }
        
    // === 不管启动结果，强制进入账单页 ===
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
     
   // === 10. 执行续期 ===
    console.log("⚡ 正在执行续期点击...");
    await renewBtn.click();

    // === 11. 等待接口返回并处理（源代码中使用了 fetch，这里等待页面响应） ===
    // 等待 8 秒让后端处理，并留心观察页面是否出现了错误提示
    await page.waitForTimeout(8000); 
    
    // 检查页面上是否弹出了这个错误文本（通常是红色提示框）
    const errorMsg = await page.locator('.toast-error, .alert-danger').textContent().catch(() => '');
    const isMaxedOut = errorMsg.includes('5 días') || beforeHours >= 120;

    await page.reload({ waitUntil: "networkidle" });

    
    // === 12. 再次等待数据刷新 ===
    await page.waitForFunction(sel => {
      const el = document.querySelector(sel);
      return el && /\d+/.test(el.textContent);
    }, timeSelector);
    
    // === 12.1 获取续期后时间 ===
    const afterHoursText = await page.textContent(timeSelector);
    const afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;

    // === 13. 最终通知 (根据接口反馈优化) ===
    if (afterHours > beforeHours) {
        // 场景 A：成功增加时间
        const message = `🎉 <b>GreatHost 续期成功</b>\n\n` +
                        `🆔 <b>ID:</b> <code>${serverId}</code>\n` +
                        `⏰ <b>时间:</b> ${beforeHours} ➔ ${afterHours}h\n` +
                        `🚀 <b>状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行正常'}\n` + 
                        `📅 <b>执行时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`; 
        await sendTelegramMessage(message);
        console.log("✅ 续期成功 ✅   ");
    } else if (isMaxedOut) {
        // 场景 B：因为满 120 小时而被拒绝（这就是你看到的 No puedes renovar...）
        const message = `✅ <b>GreatHost 已达上限</b>\n\n` +
                        `🆔 <b>ID:</b> <code>${serverId}</code>\n` +
                        `⏰ <b>当前:</b> ${beforeHours}h (已满额)\n` +
                        `🚀 <b>状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行正常'}\n` +
                        `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}\n` +      
                        `💡 <b>提示:</b> 累计不能超过 5 天，无需续期。`;
        await sendTelegramMessage(message);
        console.log("⚠️  累计不能超过 5 天，无需续期 ⚠️  ");
    } else {
        // 场景 C：真正的失败（比如网络问题或按钮点不动）
        const message = `⚠️ <b>GreatHost 续期未生效</b>\n\n` +
                        `🆔 <b>ID:</b> <code>${serverId}</code>\n` +
                        `⏰ <b>当前:</b> ${beforeHours}h\n` +
                        `🚀 <b>服务器状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行中'}\n` +
                        `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}\n` +
                        `💡 <b>提示:</b> 时间未增加，请手动检查确认。`;            
        await sendTelegramMessage(message);    
        console.log("🚨 续期失败 🚨 ");
    }  
  } catch (err) {
    console.error("❌ 运行时错误:", err.message);
    await sendTelegramMessage(`🚨 <b>GreatHost 脚本报错</b>\n<code>${err.message}</code> 🚨`);
  } finally {
    await browser.close();
  }
})();
