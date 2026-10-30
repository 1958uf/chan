import { test, expect } from '@playwright/test';

// 功能：真实连接演示份额后端；输入：显式模式与本地服务；输出：目录/类别/周期/导出交互验收。
test.describe('份额主线真实后端', () => {
  test.skip(process.env.ETF_REAL_BACKEND !== '1', '需要真实本地演示后端，不用mock冒充');

  test('份额首页展示类别，周月切换与类别详情可工作', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/');
    await expect(page.getByRole('heading', { name: '份额总览', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: '沪深300', exact: true })).toBeVisible();
    await page.getByLabel('比较周期').selectOption('week');
    await expect(page.getByRole('link', { name: '沪深300', exact: true })).toBeVisible();
    await page.getByLabel('比较周期').selectOption('month');
    await page.getByRole('link', { name: '沪深300', exact: true }).click();
    await expect(page.getByRole('heading', { name: '沪深300 · 全产品份额' })).toBeVisible();
    await expect(page.getByText('159919').first()).toBeVisible();
    expect(errors).toEqual([]);
    await page.screenshot({ path: 'artifacts/real-shares-group.png', fullPage: true });
  });

  test('目录发现与份额历史有清晰来源，纯份额导出可下载', async ({ page }) => {
    await page.goto('/#/catalogue');
    await expect(page.getByRole('heading', { name: 'ETF 发现目录' })).toBeVisible();
    await expect(page.locator('tbody').getByText('候选待核验', { exact: true }).first()).toBeVisible();
    await page.goto('/#/history');
    await expect(page.getByRole('heading', { name: /份额历史/ })).toBeVisible();
    await expect(page.getByText(/演示/).first()).toBeVisible();
    const session = await page.request.get('/api/session');
    expect(session.ok()).toBe(true);
    const exportResponse = await page.request.get('/api/shares/export?format=csv');
    expect(exportResponse.status()).toBe(200);
    expect(await exportResponse.text()).toContain('delta_shares');
  });
});
