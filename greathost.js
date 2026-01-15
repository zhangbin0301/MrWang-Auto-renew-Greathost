const EMAIL = process.env.GREATHOST_EMAIL || '';
const PASSWORD = process.env.GREATHOST_PASSWORD || '';
const CHAT_ID = process.env.CHAT_ID || '';
const BOT_TOKEN = process.env.BOT_TOKEN || '';
// === SOCKS5 代理配置 ===
const PROXY_URL = (process.env.PROXY_URL || "").trim();

// 🛑 核心修改：使用 firefox 避开 Chromium 的 SOCKS5 认证限制
const { firefox } = require("playwright");
const https = require('https');

async function sendTelegramMessage(message) {
    return new Promise((resolve) => {
        const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
        const data = JSON.stringify({ chat_id: CHAT_ID, text: message, parse_mode: 'HTML' });
        const options = { 
            method: 'POST', 
            headers: { 
                'Content-Type': 'application/json', 
                'Content-Length': Buffer.byteLength(data) 
            } 
        };
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
    const BILLING_URL = `${GREATHOST_URL}/billing/free-servers`;
    
    let proxyStatusTag = "🌐 直连模式";
    let serverStarted = false;

    // --- 1. 代理解析（稳固版） ---
    let proxyData = null;
    if (PROXY_URL && PROXY_URL.trim().length > 0) {
        try {
            let cleanUrl = PROXY_URL.trim();
            if (!cleanUrl.startsWith('socks')) cleanUrl = `socks5://${cleanUrl}`;
            proxyData = new URL(cleanUrl);
            proxyStatusTag = `🔒 代理模式 (${proxyData.host})`;
        } catch (e) {
            console.error("❌ PROXY_URL 解析失败:", e.message);
        }
    }

    let browser;
    try {
        console.log(`🚀 任务启动 | ${proxyStatusTag}`);
        
        // --- 2. 启动 Firefox ---
        const launchOptions = { headless: true };
        if (proxyData) {
            launchOptions.proxy = { server: `socks5://${proxyData.host}` };
        }
        browser = await firefox.launch(launchOptions);

        const context = await browser.newContext({
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
            viewport: { width: 1280, height: 720 },
            locale: 'es-ES'
        });

        // --- 3. 注入认证 ---
        if (proxyData && proxyData.username) {
            await context.setHttpCredentials({
                username: proxyData.username,
                password: proxyData.password
            });
        }

        const page = await context.newPage();

        // --- 4. 抹除特征 ---
        await page.addInitScript(() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
        });

        // --- 5. IP 检测 ---
        if (proxyData) {
            console.log("🌍 [Check] 正在检测代理 IP...");
            try {
                await page.goto("https://api.ipify.org?format=json", { timeout: 45000 });
                console.log(`✅ 当前出口 IP: ${await page.innerText('body')}`);
            } catch (e) {
                console.warn("⚠️ IP 检测超时，尝试继续执行主逻辑...");
            }
        }

        // --- 6. 登录流程（还原） ---
        console.log("🔑 登录中...");
        await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded" });
        await page.fill('input[name="email"]', EMAIL);
        await page.fill('input[name="password"]', PASSWORD);
        await Promise.all([
            page.click('button[type="submit"]'),
            page.waitForNavigation({ waitUntil: "networkidle" }),
        ]);
        console.log("✅ 登录成功！");

        // --- 7. 首页开机检查（还原） ---
        await page.goto(HOME_URL, { waitUntil: "networkidle" });
        const offlineIndicator = page.locator('span.badge-danger, .status-offline').first();
        if (await offlineIndicator.isVisible()) {
            const startBtn = page.locator('button.btn-start, button:has-text("Start")').first();
            if (await startBtn.isVisible()) {
                await startBtn.click();
                serverStarted = true;
                await page.waitForTimeout(2000);
            }
        }

        // --- 8. 续期流程（还原为你原来的点击写法） ---
        console.log("🔍 进入 Billing...");
        // 这里的点击方式恢复为你最开始能跑通的逻辑
        await page.locator('.btn-billing-compact').first().click();
        await page.waitForNavigation({ waitUntil: "networkidle" });

        console.log("🔍 进入 View Details...");
        // 恢复原有的 Role 选择器
        await page.getByRole('link', { name: 'View Details' }).first().click();
        await page.waitForNavigation({ waitUntil: "networkidle" });
        
        const serverId = page.url().split('/').pop() || 'unknown';
        const timeSelector = '#accumulated-time';

        // 获取时长（还原）
        const beforeHoursText = await page.textContent(timeSelector);
        const beforeHours = parseInt(beforeHoursText.replace(/[^0-9]/g, '')) || 0;

        const renewBtn = page.locator('#renew-free-server-btn');
        const btnContent = await renewBtn.innerHTML();

        if (btnContent.includes('Wait')) {
            const waitTime = btnContent.match(/\d+/)?.[0] || "??";
            console.log(`⏳ 还在冷却，需等 ${waitTime} 分钟`);
            // 这里可以调用你的 TG 发送函数...
            return;
        }

        // --- 9. 点击续期 ---
        console.log("⚡ 执行续期...");
        await page.mouse.wheel(0, 300);
        await page.waitForTimeout(2000);
        await renewBtn.click({ force: true });

        // --- 10. 校验结果 ---
        await page.waitForTimeout(20000);
        await page.reload();
        const afterHoursText = await page.textContent(timeSelector);
        const afterHours = parseInt(afterHoursText.replace(/[^0-9]/g, '')) || 0;
        
        console.log(`🎉 续期完成！时长：${beforeHours}h -> ${afterHours}h`);

    } catch (err) {
        console.error("❌ 脚本运行崩溃:", err.message);
    } finally {
        if (browser) await browser.close();
    }
})();
