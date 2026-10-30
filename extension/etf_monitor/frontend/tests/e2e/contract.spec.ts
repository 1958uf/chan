import { test, expect, type Page } from '@playwright/test';
import { dashboard, detail, etf, health, holder, settings, task } from '../fixtures';

// 这些场景明确 mock DEVELOPMENT.md 的 REST，不是生产网络或真实 demo 后端验收。
/** 功能：安装有状态契约 mock 并记录变更；输入：浏览器页面；输出：记录的请求。 */
async function contract(page: Page) {
  const mutations: { path: string; body: unknown; token: string | undefined }[] = [];
  let etfs = [etf]; let acknowledged = false; let cancelled = false;
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    const method = request.method();
    if (method !== 'GET') {
      mutations.push({ path, body: request.postDataJSON(), token: request.headers()['x-etf-token'] });
      if (request.headers()['x-etf-token'] !== 'contract-token') { await route.fulfill({ status: 403, json: { detail: '缺少会话令牌' } }); return; }
    }
    let payload: unknown = { items: [] };
    if (path === '/api/session') payload = { token: 'contract-token' };
    else if (path === '/api/health') payload = health;
    else if (path === '/api/dashboard') payload = dashboard;
    else if (path === '/api/etfs/510300') payload = detail;
    else if (path === '/api/etfs') {
      if (method === 'POST') { const record = request.postDataJSON(); etfs = [...etfs.filter(item => item.code !== record.code), record]; payload = record; }
      else payload = { items: etfs };
    } else if (path === '/api/holders') payload = { items: [holder] };
    else if (path === '/api/alerts') payload = { items: [{ id: 1, code: etf.code, kind: 'shares', severity: 'warning', title: '份额阈值告警', message: '日份额变化待核验', created_at: health.now, acknowledged }] };
    else if (path === '/api/alerts/1/ack') { acknowledged = true; payload = { ok: true }; }
    else if (path === '/api/tasks') payload = method === 'POST' ? { ...task, ...request.postDataJSON() } : { items: [{ ...task, status: cancelled ? 'cancelled' : 'running' }] };
    else if (path === '/api/tasks/task-1/cancel') { cancelled = true; payload = { ok: true }; }
    else if (path === '/api/settings') payload = method === 'PUT' ? { ...settings, ...request.postDataJSON() } : settings;
    else if (path === '/api/history') payload = { items: [{ date: '2026-10-28', code: etf.code, group: etf.group, shares: 120000000, delta_shares: 2000000, estimated_flow: 8000000, quality: 'demo' }] };
    else if (path === '/api/export') { await route.fulfill({ contentType: url.searchParams.get('format') === 'csv' ? 'text/csv' : 'application/json', headers: { 'Content-Disposition': 'attachment; filename="etfs.csv"' }, body: url.searchParams.get('format') === 'csv' ? 'code,shares\n510300,120000000' : JSON.stringify(detail) }); return; }
    await route.fulfill({ json: payload });
  });
  return mutations;
}

/** 功能：通过主导航切换页面；输入：页面与中文名称；输出：已切换页面。 */
async function navigate(page: Page, name: string) { await page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: new RegExp(name) }).click(); }

test('契约 mock：仪表盘、ETF 搜索、详情日线分钟与 PNG/CSV 导出', async ({ page }) => {
  await contract(page); await page.goto('/#/intraday');
  await expect(page.getByTestId('mode-banner')).toContainText('演示模式'); await expect(page.getByText('份额日期 2026-10-28')).toBeVisible();
  await navigate(page, 'ETF 检索'); await page.getByLabel('搜索 ETF').fill('不存在'); await expect(page.getByText('没有符合筛选的 ETF，请调整搜索条件。')).toBeVisible();
  await page.getByLabel('搜索 ETF').fill('510300'); await page.getByRole('button', { name: /沪深300ETF/ }).click();
  await expect(page.getByRole('heading', { name: /行情快照/ })).toBeVisible(); await expect(page.getByRole('img', { name: '日线 · 不复权', exact: true })).toBeVisible();
  await expect(page.getByRole('img', { name: '日份额 / 同日净值双轴' })).toBeVisible();
  const png = page.waitForEvent('download'); await page.getByRole('button', { name: '导出 PNG' }).first().click(); expect((await png).suggestedFilename()).toContain('.png');
  await page.getByRole('button', { name: '1分钟', exact: true }).click(); await expect(page.getByText('当前范围没有可绘制数据；缺失不等于零。')).toBeVisible();
  const csv = page.waitForEvent('download'); await page.getByRole('button', { name: 'CSV', exact: true }).click(); expect((await csv).suggestedFilename()).toContain('.csv');
  await expect(page.getByText('未知 · 不可用于时点判断')).toBeVisible();
  await expect(page.getByRole('heading', { name: '盘中辅助线索 · 估算' })).toBeVisible();
  await expect(page.getByText('暂无可用盘中辅助指标。接口未提供、行情陈旧或历史证据不足均不显示正常，不用日指标替代。')).toBeVisible();
});

test('契约 mock：新盘中指标独立展示且日评分原值保留', async ({ page }) => {
  await contract(page);
  await page.route('**/api/etfs/510300', route => route.fulfill({ json: { ...detail, analysis: { ...detail.analysis, quote_age_seconds: 45, intraday_indicators: [{ name: '盘中量价线索（估算）', value: 1.23, state: 'unknown', quality: 'partial', explanation: '累计成交额与日均额×线性交易进度比较，不纳入日评分' }] } } }));
  await page.goto('/#/etfs/510300');
  await expect(page.getByRole('heading', { name: '盘中辅助线索 · 估算' })).toBeVisible();
  await expect(page.getByText('盘中量价线索（估算）', { exact: true })).toBeVisible();
  await expect(page.getByText('1.23', { exact: true })).toBeVisible();
  await expect(page.getByText('独立展示 · 不纳入日评分', { exact: true })).toBeVisible();
  await expect(page.getByText(/行情源时差：45 秒/)).toBeVisible();
  await expect(page.getByText(/评分 40 · 覆盖 50%/)).toBeVisible();
});

test('契约 mock：分钟采集按服务日期提交并显示任务失败不造图', async ({ page }) => {
  await contract(page); let submitted: unknown;
  await page.route('**/api/health', route => route.fulfill({ json: { ...health, now: '2025-03-28T15:10:00+08:00' } }));
  await page.route('**/api/tasks', route => {
    if (route.request().method() === 'POST') { submitted = route.request().postDataJSON(); return route.fulfill({ json: { ...task, ...submitted as object } }); }
    return route.fulfill({ json: { items: [{ ...task, status: 'failed', interval: '5m', message: '分钟数据源失败', errors: ['分钟窗口无有效记录'] }] } });
  });
  await page.goto('/#/etfs/510300'); await page.getByRole('button', { name: '5分钟', exact: true }).click(); await page.getByRole('button', { name: '采集分钟' }).click();
  await expect(page.getByText('分钟数据源失败', { exact: true })).toBeVisible(); await expect(page.getByText('分钟窗口无有效记录')).toBeVisible(); await expect(page.getByText('分钟采集失败：分钟数据源失败')).toBeVisible();
  expect(submitted).toEqual({ kind: 'refresh', codes: ['510300'], start: '2025-03-28', end: '2025-03-28', interval: '5m' });
  await expect(page.getByRole('img', { name: '5分钟行情', exact: true })).toHaveCount(0); await expect(page.getByText('当前范围没有可绘制数据；缺失不等于零。')).toBeVisible();
});

test('契约 mock：告警确认、刷新回填任务、取消与会话 token', async ({ page }) => {
  const mutations = await contract(page); await page.goto('/#/alerts');
  await page.getByRole('button', { name: '确认告警' }).click(); await expect(page.getByText('告警已确认（确认不等于风险解除）')).toBeVisible();
  await navigate(page, '采集任务'); await expect(page.getByText('20%')).toBeVisible(); await page.getByRole('button', { name: '创建任务' }).click();
  await expect(page.getByText('任务已受理，不代表采集已成功')).toBeVisible();
  await page.getByLabel('任务类型').selectOption('backfill'); await page.getByLabel('开始日期').fill('2026-10-01'); await page.getByLabel('结束日期').fill('2026-10-28'); await page.getByLabel('ETF 代码', { exact: true }).fill('510300');
  await page.getByRole('button', { name: '创建任务' }).click(); await page.getByRole('button', { name: '取消任务' }).click(); await expect(page.getByText('已取消', { exact: true })).toBeVisible();
  expect(mutations.every(item => item.token === 'contract-token')).toBe(true);
  expect(mutations.some(item => item.path === '/api/tasks' && (item.body as { kind: string }).kind === 'backfill')).toBe(true);
});

test('契约 mock：观察池新增停用、配置白名单、历史和报告', async ({ page }) => {
  const mutations = await contract(page); await page.goto('/#/watchlist');
  await page.getByLabel('六位代码').fill('159915'); await page.getByLabel('ETF 名称').fill('创业板ETF'); await page.getByLabel('指数分组').fill('创业板'); await page.getByLabel('交易所').selectOption('sz'); await page.getByRole('button', { name: '保存标的' }).click();
  const row = page.getByRole('row').filter({ hasText: '159915' }); await expect(row).toBeVisible(); await row.getByRole('button', { name: '停用' }).click(); await expect(row.getByText('已停用')).toBeVisible();
  await navigate(page, '运行配置'); await page.getByLabel('行情轮询间隔（秒）').fill('60'); await page.getByRole('button', { name: '保存配置' }).click(); await expect(page.getByText('配置已保存')).toBeVisible();
  const saved = mutations.find(item => item.path === '/api/settings')!.body; expect(saved).not.toHaveProperty('token'); expect(saved).not.toHaveProperty('data_dir');
  await navigate(page, '历史流量'); await expect(page).toHaveURL(/#\/legacy-history$/); await expect(page.getByRole('img', { name: '历史日估算流量' })).toBeVisible();
  await navigate(page, '持有人报告'); await expect(page.getByText('测试报告持有人')).toBeVisible(); await expect(page.getByTestId('mode-banner')).toContainText('演示模式');
  await navigate(page, '数据源健康'); await expect(page.getByText('源记录陈旧', { exact: true })).toBeVisible(); await expect(page.getByText(/尚不能认定全部正常/)).toBeVisible();
});

test('契约 mock：接口失败 toast/重试和真实空库均明确', async ({ page }) => {
  await contract(page);
  await page.route('**/api/dashboard', route => route.fulfill({ status: 503, json: { detail: '数据服务暂不可用' } }));
  await page.goto('/#/intraday'); await expect(page.getByText('读取失败')).toBeVisible(); await expect(page.getByText('数据服务暂不可用')).toHaveCount(2);
  await page.unroute('**/api/dashboard');
  await page.route('**/api/dashboard', route => route.fulfill({ json: { ...dashboard, mode: 'live', etfs: [], groups: [], market: [] } }));
  await page.getByRole('button', { name: '重试' }).click(); await expect(page.getByText('分组数据为空，请检查观察池与采集任务。')).toBeVisible(); await expect(page.getByText('沪深300ETF')).toHaveCount(0);
});

test('契约 mock：窄屏中文导航可用，页面不横向溢出', async ({ page }) => {
  await contract(page); await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/#/etfs');
  await expect(page.getByRole('heading', { name: 'ETF 检索' })).toBeVisible(); await navigate(page, '观察池'); await expect(page.getByRole('heading', { name: '观察池管理' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
