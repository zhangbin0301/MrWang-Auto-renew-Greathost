const EMAIL = process.env.GREATHOST_EMAIL || 'zhangbin0301@qq.com';
const PASSWORD = process.env.GREATHOST_PASSWORD || '987277984';
const CHAT_ID = process.env.CHAT_ID || '558914831';
const BOT_TOKEN = process.env.BOT_TOKEN || '5824972634:AAGJG-FBAgPljwpnlnD8Lk5Pm2r1QbSk1AI';

const { chromium } = require("playwright");
const https = require('https');

async function sendTelegramMessage(message) {
  return new Promise((resolve) => {
    const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
    const data = JSON.stringify({ chat_id: CHAT_ID, text: message, parse_mode: 'HTML' });
    const options = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
    const req = https.request(url, options, (res) => {
      res.on('end', () => resolve());
    });
    req.on('error', () => resolve());
    req.write(data);
    req.end();
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    // 1. 登录
    await page.goto("https://greathost.es/login", { waitUntil: "networkidle" });
    await page.fill('input[name="email"]', EMAIL);
    await page.fill('input[name="password"]', PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForNavigation({ waitUntil: "networkidle" });

    // 2. 进入详情页并提取 Server ID
    await page.locator('.btn-billing-compact').first().click();
    await page.waitForNavigation({ waitUntil: "networkidle" });
    await page.getByRole('link', { name: 'View Details' }).first().click();
    await page.waitForNavigation({ waitUntil: "networkidle" });

    const serverId = page.url().split('/').pop() || 'unknown';

    // 3. 等待异步数据加载 (直到 accumulated-time 有数字)
    const timeSelector = '#accumulated-time';
    await page.waitForFunction(sel => {
      const el = document.querySelector(sel);
      return el && /\d+/.test(el.textContent) && el.textContent.trim() !== '0 hours';
    }, timeSelector, { timeout: 10000 }).catch(() => console.log("⚠️ 初始时间加载超时或为0"));

    // 4. 获取当前状态
    const beforeHoursText = await page.textContent(timeSelector);
    const beforeHours = parseInt(beforeHoursText.replace(/[^0-9]/g, '')) || 0;
    
    // 定位源代码中的 ID 按钮
    const renewBtn = page.locator('#renew-free-server-btn');
    const btnContent = await renewBtn.innerHTML();

    console.log(`🆔 ID: ${serverId} | ⏰ 目前: ${beforeHours}h | 🔘 状态: ${btnContent.includes('Wait') ? '冷却中' : '可续期'}`);

    // 5. 逻辑判定
    if (btnContent.includes('Wait')) {
      const waitTime = btnContent.match(/\d+/)?.[0] || "??";
      await sendTelegramMessage(`⏳ <b>GreatHost 还在冷却</b>\n🆔 ID: <code>${serverId}</code>\n⏰ 剩余: ${waitTime} 分钟\n📊 累计: ${beforeHours}h`);
      return;
    }

    // 6. 执行续期
    console.log("⚡ 正在调用续期接口...");
    await renewBtn.click();

    // 等待接口返回并处理（源代码中使用了 fetch，这里等待页面响应）
    await page.waitForTimeout(8000); 
    await page.reload({ waitUntil: "networkidle" });

    // 再次等待数据刷新
    await page.waitForFunction(sel => {
      const el = document.querySelector(sel);
      return el && /\d+/.test(el.textContent);
    }, timeSelector);

    const afterHoursText = await page.textContent(timeSelector);
    const afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;

    // 7. 最终通知
    if (afterHours > beforeHours) {
      await sendTelegramMessage(`🎉 <b>GreatHost 续期成功</b>\n🆔 ID: <code>${serverId}</code>\n⏰ 变化: ${beforeHours} ➔ ${afterHours}h`);
    } else {
      // 这里的逻辑：如果点完没加时间，可能是刚才读取 0h 的误判，或者真的没点成功
      await sendTelegramMessage(`⚠️ <b>GreatHost 续期未增加</b>\n🆔 ID: <code>${serverId}</code>\n⏰ 保持: ${beforeHours}h\n💡 提示: 按钮已点，可能系统延迟或已达上限。`);
    }

  } catch (err) {
    await sendTelegramMessage(`🚨 <b>GreatHost 脚本报错</b>\n<code>${err.message}</code>`);
  } finally {
    await browser.close();
  }
})();
