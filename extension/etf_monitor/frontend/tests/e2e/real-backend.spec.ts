import { test, expect } from '@playwright/test';

// 功能：实际连接独立demo后端而非mock；输入：已启动的本地服务；输出：真实页面交互验收。
test.describe('真实演示后端集成', () => {
  test.skip(process.env.ETF_REAL_BACKEND !== '1', '需要显式开启并启动独立演示后端，不用mock替代');

  test('份额首页与核心类别使用真实API，始终显示演示标签', async ({ page }) => {
    const failures: string[] = [];
    page.on('pageerror', error => failures.push(error.message));
    await page.goto('/');
    await expect(page.getByText(/演示/).first()).toBeVisible();
    await expect(page.getByRole('link', { name: '上证50', exact: true }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: '创业板', exact: true }).first()).toBeVisible();
    expect(failures).toEqual([]);
    await page.screenshot({ path: 'artifacts/real-demo-dashboard.png', fullPage: true });
    await page.goto('/#/etfs/159915');
    await expect(page.getByText('易方达创业板ETF').first()).toBeVisible();
    await expect(page.getByText(/演示/).first()).toBeVisible();
    await page.screenshot({ path: 'artifacts/real-demo-detail.png', fullPage: true });
  });

  test('真实报告与配置页面可用，观察池数据来自API', async ({ page }) => {
    await page.goto('/#/tasks');
    await expect(page.getByText('采集任务').last()).toBeVisible();
    await page.goto('/#/history');
    await expect(page.getByText(/历史/).first()).toBeVisible();
    await page.goto('/#/holders');
    await expect(page.getByText(/报告期/).first()).toBeVisible();
    await page.goto('/#/watchlist');
    await expect(page.getByText('159915').first()).toBeVisible();
    await page.goto('/#/health');
    await expect(page.getByText(/数据源健康/).first()).toBeVisible();
  });

  test('通过真实API完成任务并下载CSV，缺令牌请求被拒绝', async ({ page }) => {
    await page.goto('/#/tasks');
    await page.getByRole('button', { name: '创建任务' }).click();
    await expect(page.getByText(/任务已受理/).first()).toBeVisible();
    await page.goto('/#/etfs/159915');
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'CSV', exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
    const denial = await page.request.post('/api/tasks', { data: { kind: 'refresh' }, headers: { Origin: 'http://127.0.0.1:8765' } });
    expect(denial.status()).toBe(403);
  });
});
