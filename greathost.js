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
    
    // 1. 获取当前状态文字
    const statusText = await page.locator('.status-text, .server-status').first().textContent().catch(() => 'unknown');
    const statusLower = statusText.trim().toLowerCase();
    
    // 2. 执行判定与点击动作
    if (statusLower.includes('offline') || statusLower.includes('stopped') || statusLower.includes('离线')) {
        console.log(`⚡ 检测到离线 [${statusText}]，尝试触发启动...`);
        
        try {
            // 使用 SVG 结构精准定位三角形启动按钮
            const startBtn = page.locator('button.btn-start[title="Start Server"]').first();
            const isDisabled = await startBtn.getAttribute('disabled');

            if (await startBtn.isVisible() && isDisabled === null) {
                await startBtn.click();
                // 注意：请确保你在 try 块的最顶部（或登录前）已经写了 let serverStarted = false;
                serverStarted = true; 
                console.log("✅ 启动指令已发出");
                await page.waitForTimeout(1000); // 仅做短暂缓冲
            } else {
                console.log("⚠️ 启动按钮不可见或已被禁用，跳过启动动作。");
            }
        } catch (e) {
            console.log("ℹ️ 尝试启动时遇到错误，忽略并继续后续流程...");
        }
    } else if (statusLower.includes('pending')) {
        console.log("⏳ 服务器正在启动中 (Pending)，无需操作。");
    } else {
        console.log(`ℹ️ 服务器当前状态为 [${statusText}]，运行正常。`);
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
    console.log("⚡ 正在调用续期接口...执行续期...");
    await renewBtn.click();
    
    // === 11. 等待接口返回并处理（源代码中使用了 fetch，这里等待页面响应） ===
    await page.waitForTimeout(8000); 
    await page.reload({ waitUntil: "networkidle" });
    
    // === 12. 再次等待数据刷新 ===
    await page.waitForFunction(sel => {
      const el = document.querySelector(sel);
      return el && /\d+/.test(el.textContent);
    }, timeSelector);

    const afterHoursText = await page.textContent(timeSelector);
    const afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;

    // === 12. 最终通知 ===
if (afterHours > beforeHours) {
    const message = `🎉 <b>GreatHost 续期成功</b>\n\n` +
                    `🆔 <b>服务器ID:</b> <code>${serverId}</code>\n` +
                    `⏰ <b>时间变化:</b> ${beforeHours} ➔ ${afterHours}h (+12h)\n` +
                    `🚀 <b>服务器状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行中'}\n` +
                    `📅 <b>执行时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`;
    
    await sendTelegramMessage(message);
    console.log("🎉 续期成功 🎉");
} else {
      const message = `⚠️ <b>GreatHost 续期未生效</b>\n\n` +
                      `🆔 <b>服务器ID:</b> <code>${serverId}</code>\n` +
                      `⏰ <b>当前时间:</b> ${beforeHours}h\n` +
                      `🚀 <b>服务器状态:</b> ${serverStarted ? '✅ 已触发启动' : '运行中'}\n` +
                      `📅 <b>检查时间:</b> ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}\n` +
                      `💡 <b>提示:</b> 时间未增加，请检查手动确认。`;
      await sendTelegramMessage(message);
      console.log("🚨 续期失败 🚨 ");
    }  
  } catch (err) {
    console.error("❌ 运行时错误:", err.message);
    await sendTelegramMessage(`🚨 <b>GreatHost 脚本报错</b>\n<code>${err.message}</code>`);
  } finally {
    await browser.close();
  }
})();
