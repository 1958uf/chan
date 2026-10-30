import { defineConfig, devices } from '@playwright/test';

// 功能：运行浏览器主要场景；输入：可选现有前端地址；输出：Playwright 配置。
// 浏览器由主代理准备，本配置不安装浏览器；默认场景 mock REST 契约，不宣称真实后端集成通过。
export default defineConfig({
  testDir: './tests/e2e', timeout: 30000, fullyParallel: false,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: process.env.ETF_FRONTEND_URL || 'http://127.0.0.1:5173', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], launchOptions: { channel: process.env.ETF_BROWSER_CHANNEL || undefined } } }],
  webServer: process.env.ETF_FRONTEND_URL ? undefined : {
    command: 'npm.cmd run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: true, timeout: 120000,
  },
});
