import { test, expect, type Download, type Locator, type Page, type Request } from '@playwright/test';
import { health } from '../fixtures';

// 仅测试固定 REST 契约；不连接真实采集源，不替代 real-backend.spec.ts 的集成验收。
// 本机 Edge 同时核验筛选、真实图表和下载；给予完整流程时间，不用固定休眠规避等待。
test.describe.configure({ timeout: 60000 });
const groupName = '沪深300 / 核心';
const bondGroup = '国债';
const asOf = '2026-10-28';
const token = 'shares-contract-token';
type Period = 'day' | 'week' | 'month';
const periodNames: Record<Period, string> = { day: '日', week: '周', month: '月' };
const notice = '契约口径：同一可比集合计算增减；候选不混入已确认分母，缺失不等于零。';
const product = { code: '510300', name: '契约核心ETF甲', group: groupName, asset_class: '宽基', shares: 120000000, trade_date: asOf, delta_shares: 20000000, delta_pct: 20, delta_5d: null, delta_20d: null, increase_streak: 2, decrease_streak: 0, classification_status: 'confirmed', quality: 'partial', reason: '长期基线不足', source: '固定份额契约源' };
const products = [
  product,
  { ...product, code: '510310', name: '契约核心ETF乙', shares: 80000000, delta_shares: null, delta_pct: null, increase_streak: null, decrease_streak: null, reason: '首尾基线缺失' },
  { ...product, code: '510330', name: '契约全缺份额ETF', shares: null, trade_date: null, delta_shares: null, delta_pct: null, increase_streak: null, decrease_streak: null, quality: 'missing', reason: '从未采集份额' },
  { ...product, code: '511010', name: '契约国债ETF', group: bondGroup, asset_class: '债券', shares: 300000000, delta_shares: -10000000, delta_pct: -3.23, increase_streak: 0, decrease_streak: 3 },
];
const candidate = { code: '159919', name: '契约候选ETF', group: groupName, asset_class: '宽基', exchange: 'sz', enabled: true, tags: [], classification_status: 'candidate', classification_evidence: '仅候选名称规则，未核验基金文件', tracking_index: null, catalogue_source: '固定交易所目录契约源', discovered_at: health.now, manual_classification: false };
const catalogueItems = [
  ...products.map(item => ({ code: item.code, name: item.name, group: item.group, asset_class: item.asset_class, exchange: 'sh', enabled: true, tags: [], classification_status: 'confirmed', classification_evidence: '固定测试基金文件索引', tracking_index: item.group, catalogue_source: candidate.catalogue_source, discovered_at: health.now, manual_classification: false })),
  candidate,
];
const summaries = [
  { group: groupName, asset_class: '宽基', total_shares: 200000000, delta_shares: 20000000, delta_pct: 20, increased: 1, decreased: 0, unchanged: 0, missing_count: 1, candidate_count: 1, total_count: 3, available_count: 2, comparable_count: 1, coverage_pct: 33.33, trade_date: asOf, quality: 'partial' },
  { group: bondGroup, asset_class: '债券', total_shares: 300000000, delta_shares: -10000000, delta_pct: -3.23, increased: 0, decreased: 1, unchanged: 0, missing_count: 0, candidate_count: 0, total_count: 1, available_count: 1, comparable_count: 1, coverage_pct: 100, trade_date: asOf, quality: 'partial' },
];
interface RecordedRequest { path: string; method: string; query: Record<string, string>; body: Record<string, unknown> | null; token?: string }
interface MockOptions { empty?: boolean; mode?: 'live' | 'demo'; unknownMode?: boolean; unknownCoverage?: boolean; sessionToken?: string; failedTask?: boolean }

/** 功能：创建固定日周月期末历史；输入：频率；输出：包含多线、空点与原始份单位的历史记录。 */
function historyItems(frequency: Period) {
  const dates = frequency === 'day' ? ['2026-10-26', '2026-10-27', asOf] : frequency === 'week' ? ['2026-10-16', '2026-10-23', asOf] : ['2026-08-31', '2026-09-30', asOf];
  return products.flatMap((item, index) => dates.map((date, point) => ({ date, code: item.code, name: item.name, group: item.group, asset_class: item.asset_class, total_shares: index === 2 || (index === 0 && point === 1) ? null : [100000000, 110000000, item.shares][point], delta_shares: index === 2 || point < 2 ? null : item.delta_shares, delta_pct: index === 2 || point < 2 ? null : item.delta_pct, comparable_count: index === 2 ? null : 1, total_count: 1, coverage_pct: index === 2 ? null : 100, quality: index === 2 || (index === 0 && point === 1) ? 'missing' : 'partial', reason: index === 2 ? '从未采集份额' : point === 1 && index === 0 ? '该期缺数' : '', source: product.source })));
}

/** 功能：按固定契约安装有状态 mock；输入：页面与空库/模式/鉴权选项；输出：请求、错误及目录任务状态。 */
async function sharesContract(page: Page, options: MockOptions = {}) {
  const requests: RecordedRequest[] = [];
  const unexpected: string[] = [];
  const failures = new Map<string, { status: number; detail: string }>();
  let catalogue = structuredClone(catalogueItems);
  const tasks: Record<string, unknown>[] = [];
  const mode = options.mode || 'demo';
  /** 功能：根据 query 筛选对象；输入：记录数组、查询参数；输出：匹配分类、组、代码与关键词的记录。 */
  const filter = <T extends { group: string; asset_class?: string; code?: string; name?: string; classification_status?: string }>(items: T[], query: Record<string, string>): T[] => items.filter(item =>
    (!query.group || item.group === query.group) && (!query.asset_class || item.asset_class === query.asset_class) && (!query.code || item.code === query.code) && (!query.classification_status || item.classification_status === query.classification_status) && (!query.q || `${item.code} ${item.name} ${item.group}`.includes(query.q)));
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    const method = request.method(); const query = Object.fromEntries(url.searchParams);
    const body = request.postData() ? request.postDataJSON() as Record<string, unknown> : null;
    requests.push({ path, method, query, body, token: request.headers()['x-etf-token'] });
    const failure = failures.get(path);
    if (failure) { await route.fulfill({ status: failure.status, json: { detail: failure.detail } }); return; }
    if (method !== 'GET' && request.headers()['x-etf-token'] !== token) { await route.fulfill({ status: 403, json: { detail: '份额契约会话令牌无效' } }); return; }
    let payload: unknown;
    if (method === 'GET' && path === '/api/session') payload = { token: options.sessionToken ?? token };
    else if (method === 'GET' && path === '/api/health') payload = { ...health, mode: options.empty ? 'live' : mode, sources: options.empty ? [] : health.sources };
    else if (method === 'GET' && path === '/api/shares/overview') {
      const items = options.empty ? [] : filter(products, query);
      const groups = options.empty ? [] : filter(summaries, query).map(item => ({ ...item, trade_date: query.as_of || asOf, ...(options.unknownCoverage ? { available_count: null, comparable_count: null, total_count: null, candidate_count: null, missing_count: null, coverage_pct: null } : {}), ...(query.period === 'week' ? { delta_shares: item.group === groupName ? 40000000 : -20000000 } : query.period === 'month' ? { delta_shares: item.group === groupName ? 60000000 : -30000000 } : {}) }));
      payload = { as_of: options.empty ? '' : query.as_of || asOf, period: query.period || 'day', items, groups, coverage: { total_count: options.empty ? 0 : catalogue.length, available_count: options.empty ? 0 : 3, comparable_count: options.empty ? 0 : 2, missing_count: options.empty ? 0 : 1, candidate_count: options.empty ? 0 : catalogue.filter(item => item.classification_status === 'candidate').length, coverage_pct: options.empty ? null : 50 }, notice, ...(options.unknownMode ? {} : { mode: options.empty ? 'live' : mode }) };
    } else if (method === 'GET' && path.startsWith('/api/shares/groups/')) {
      const group = decodeURIComponent(path.slice('/api/shares/groups/'.length));
      const summary = summaries.find(item => item.group === group);
      if (!summary) { await route.fulfill({ status: 404, json: { detail: '份额分组不存在' } }); return; }
      payload = { group: { ...summary, trade_date: query.as_of || asOf }, items: options.empty ? [] : products.filter(item => item.group === group), mode, notice };
    } else if (method === 'GET' && path === '/api/shares/history') {
      const frequency = (query.frequency || 'day') as Period;
      const items = options.empty ? [] : filter(historyItems(frequency), query).filter(item => (!query.start || item.date >= query.start) && (!query.end || item.date <= query.end));
      payload = { items, frequency, mode: options.empty ? 'live' : mode, notice, total: items.length, calendar_complete: !options.empty };
    } else if (method === 'GET' && path === '/api/catalogue') {
      const items = options.empty ? [] : filter(catalogue, query);
      payload = { items: items.slice(Number(query.offset || 0), Number(query.offset || 0) + Number(query.limit || 100)), total: items.length, mode: options.empty ? 'live' : mode, coverage: { confirmed: options.empty ? 0 : catalogue.filter(item => item.classification_status === 'confirmed').length, candidate: options.empty ? 0 : catalogue.filter(item => item.classification_status === 'candidate').length, sources: { [candidate.catalogue_source]: options.empty ? 0 : catalogue.length }, notice: '目录发现不保证分类完整' } };
    } else if (method === 'POST' && path === '/api/catalogue/classify' && body) {
      const item = catalogue.find(item => item.code === body.code);
      if (!item) { await route.fulfill({ status: 404, json: { detail: '目录产品不存在' } }); return; }
      const updated = { ...item, ...body, manual_classification: true } as typeof item;
      catalogue = catalogue.map(item => item.code === updated.code ? updated : item); payload = updated;
    } else if (path === '/api/tasks' && method === 'POST' && body) {
      const task = { id: `shares-task-${tasks.length + 1}`, ...body, status: options.failedTask ? 'failed' : 'queued', progress: options.failedTask ? 100 : 0, message: options.failedTask ? '交易所目录采集失败' : '契约任务排队，尚未采集', errors: options.failedTask ? ['目录来源请求失败，没有有效记录'] : [], created_at: health.now, finished_at: options.failedTask ? health.now : null };
      tasks.push(task); payload = task;
    } else if (path === '/api/tasks' && method === 'GET') payload = { items: tasks };
    else { unexpected.push(`${method} ${path}`); await route.fulfill({ status: 404, json: { detail: `未约定接口：${method} ${path}` } }); return; }
    await route.fulfill({ json: payload });
  });
  return { requests, unexpected, failures, tasks };
}

/** 功能：精确匹配请求 query；输入：请求、路径、query；输出：是否符合固定契约。 */
function matches(request: Request, path: string, query: Record<string, string>): boolean {
  const url = new URL(request.url()); return request.method() === 'GET' && url.pathname === path && JSON.stringify(Object.entries(Object.fromEntries(url.searchParams)).sort()) === JSON.stringify(Object.entries(query).sort());
}
/** 功能：等待指定 query 后执行操作；输入：页面、路径、query、操作；输出：确认实际浏览器请求已发生。 */
async function queried(page: Page, path: string, query: Record<string, string>, action: () => Promise<unknown>) {
  const response = page.waitForResponse(response => matches(response.request(), path, query)); await action(); expect((await response).status()).toBe(200);
}
/** 功能：定位有标题的面板；输入：页面及标题；输出：该 section 的范围定位器。 */
function panel(page: Page, title: string): Locator { return page.locator('section').filter({ has: page.getByRole('heading', { name: title, exact: true }) }); }
/** 功能：读取真实下载到内存；输入：下载对象；输出：文件字节，不额外写入文件。 */
async function downloaded(download: Download): Promise<Buffer> {
  expect(await download.failure()).toBeNull(); const stream = await download.createReadStream(); expect(stream).not.toBeNull();
  const chunks: Buffer[] = []; for await (const chunk of stream!) chunks.push(Buffer.from(chunk)); return Buffer.concat(chunks);
}
/** 功能：导出并核验 PNG 真实签名；输入：页面、图表标题；输出：下载成功且非空 PNG。 */
async function pngDownload(page: Page, title: string) {
  const pending = page.waitForEvent('download'); await panel(page, title).getByRole('button', { name: '导出 PNG', exact: true }).click();
  const download = await pending; expect(download.suggestedFilename()).toBe(`ETF-${title}.png`);
  const bytes = await downloaded(download); expect([...bytes.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]); expect(bytes.length).toBeGreaterThan(1000);
}
/** 功能：读取已渲染 ECharts 多线实际配置；输入：页面、图表名；输出：名称、空点和断线策略，不替代真实图表渲染。 */
async function chartLines(page: Page, title: string): Promise<{ name: string; data: (number | null)[]; connectNulls: boolean }[]> {
  await expect(page.getByRole('img', { name: title, exact: true })).toBeVisible();
  return page.evaluate(async chartTitle => {
    const resource = performance.getEntriesByType('resource').map(entry => entry.name).find(name => /\/echarts(?:\.js|\?)/.test(name));
    if (!resource) throw new Error('页面未加载 ECharts 模块，不能核验真实多线配置');
    const echarts = await import(/* @vite-ignore */ resource);
    const chart = [...document.querySelectorAll('[role="img"]')].find(element => element.getAttribute('aria-label') === chartTitle);
    const instance = chart && echarts.getInstanceByDom(chart);
    if (!instance) throw new Error('图表实例未初始化');
    return instance.getOption().series.map((series: { name: string; data: (number | null)[]; connectNulls: boolean }) => ({ name: series.name, data: series.data, connectNulls: series.connectNulls }));
  }, title);
}

test('份额契约：首页保留份额主线、缺值与覆盖可比口径，筛选日周月及更新鉴权', async ({ page }) => {
  const mock = await sharesContract(page); await page.goto('/#/dashboard');
  await expect(page.getByRole('heading', { name: '份额总览', exact: true })).toBeVisible();
  await expect(page.getByTestId('mode-banner')).toContainText('演示模式'); await expect(page.getByText('份额接口 · 演示样例，不代表真实市场', { exact: true })).toBeVisible();
  await expect(page.getByText(notice, { exact: false })).toBeVisible();
  await expect(panel(page, '接口覆盖口径').getByText('首尾可比：2', { exact: true })).toBeVisible();
  const groupRow = page.getByRole('row').filter({ has: page.getByRole('link', { name: groupName, exact: true }) });
  await expect(groupRow).toContainText('同日可用 2/3 · 可比 1 · 可比覆盖 33.33%'); await expect(groupRow).toContainText('分类候选 1 · 缺失 1');
  const missingRow = page.getByRole('row').filter({ hasText: '契约全缺份额ETF' });
  await expect(missingRow.getByRole('cell').nth(1)).toContainText('—'); await expect(missingRow.getByRole('cell').nth(2)).toHaveText('—基准 未知'); await expect(missingRow.getByRole('cell').nth(5)).toContainText('— / —');
  await expect(missingRow.getByText('缺失', { exact: true })).not.toHaveClass(/good/);
  await queried(page, '/api/shares/overview', { period: 'day', as_of: asOf }, () => page.getByLabel('统计日期').fill(asOf));
  for (const period of ['week', 'month', 'day'] as const) await queried(page, '/api/shares/overview', { period, as_of: asOf }, () => page.getByRole('combobox', { name: '比较周期', exact: true }).selectOption(period));
  await queried(page, '/api/shares/overview', { period: 'day', as_of: asOf, asset_class: '宽基' }, () => page.getByRole('combobox', { name: '资产类别', exact: true }).selectOption('宽基'));
  await expect(page.getByRole('button', { name: '契约国债ETF', exact: true })).toHaveCount(0);
  await queried(page, '/api/shares/overview', { period: 'day', as_of: asOf, asset_class: '宽基', group: groupName }, () => page.getByRole('combobox', { name: '指数分组', exact: true }).selectOption(groupName));
  await page.getByRole('button', { name: '更新份额', exact: true }).click(); await expect(page.getByText('份额任务已受理，请在采集任务页核验完成状态；不会采集行情或净值', { exact: true })).toBeVisible();
  expect(mock.requests.find(item => item.method === 'POST')).toEqual({ path: '/api/tasks', method: 'POST', query: {}, body: { kind: 'shares', group: groupName, asset_class: '宽基' }, token });
  expect(mock.requests.some(item => item.path === '/api/dashboard')).toBe(false); expect(mock.unexpected).toEqual([]);
});

test('份额契约：编码分组、缺份额成员与候选分离、多线断点和日周月历史请求', async ({ page }) => {
  const mock = await sharesContract(page); await page.goto('/#/dashboard');
  await page.getByRole('link', { name: groupName, exact: true }).click(); await expect(page).toHaveURL(`/#/groups/${encodeURIComponent(groupName)}`);
  await expect(page.getByRole('heading', { name: `${groupName} · 全产品份额`, exact: true })).toBeVisible();
  await expect(panel(page, '全部成员产品（含份额缺失）').getByText('契约全缺份额ETF', { exact: true })).toBeVisible();
  await expect(panel(page, '分类候选 / 分类缺口')).toContainText(candidate.name); await expect(panel(page, '分类候选 / 分类缺口')).toContainText(candidate.classification_evidence);
  await expect(panel(page, '全部成员产品（含份额缺失）')).not.toContainText(candidate.name);
  await expect.poll(() => mock.requests.filter(item => item.path === '/api/shares/history').map(item => item.query.code).sort()).toEqual(['510300', '510310', '510330']);
  const lines = await chartLines(page, '成员份额多线对比'); expect(lines).toHaveLength(3); expect(lines[0]).toEqual({ name: product.name, data: [1, null, 1.2], connectNulls: false }); expect(lines[2].data).toEqual([null, null, null]);
  await pngDownload(page, '成员份额多线对比');
  await page.getByLabel('契约核心ETF乙 · 510310', { exact: true }).uncheck();
  await expect.poll(async () => (await chartLines(page, '成员份额多线对比')).length).toBe(2);
  for (const period of ['week', 'month'] as const) {
    const pending = page.waitForResponse(response => matches(response.request(), '/api/shares/history', { code: '510300', frequency: period, start: '2026-05-01', end: asOf }));
    await page.getByRole('combobox', { name: '比较周期', exact: true }).selectOption(period); await pending;
    await expect.poll(async () => (await chartLines(page, '成员份额多线对比'))[0].data).toEqual([1, null, 1.2]);
  }
  expect(mock.requests.some(item => item.path === `/api/shares/groups/${encodeURIComponent(groupName)}` && item.query.period === 'day')).toBe(true);
  expect(mock.requests.some(item => item.path === '/api/catalogue' && item.query.group === groupName && item.query.limit === '5000')).toBe(true);
  await queried(page, `/api/shares/groups/${encodeURIComponent(groupName)}`, { period: 'month', as_of: '2026-10-27' }, () => page.getByLabel('统计日期').fill('2026-10-27'));
  await expect(panel(page, '分组统计')).toContainText('覆盖'); expect(mock.unexpected).toEqual([]);
});

for (const frequency of ['day', 'week', 'month'] as const) {
  test(`份额契约：历史${periodNames[frequency]}期末多线、当前查询 CSV/JSON/PNG 下载与缺数保留`, async ({ page }) => {
    const mock = await sharesContract(page); await page.goto('/#/history');
    await expect(page.getByRole('heading', { name: '历史份额', exact: true })).toBeVisible();
    await expect(page.getByText('API 模式：演示（固定样例，非真实市场） · 返回频率：日', { exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: '频率', exact: true }).selectOption(frequency); await page.getByRole('combobox', { name: '指数分组', exact: true }).selectOption(groupName);
    const start = frequency === 'day' ? '2026-10-26' : frequency === 'week' ? '2026-10-16' : '2026-08-31';
    await page.getByLabel('开始日期', { exact: true }).fill(start); await page.getByLabel('结束日期', { exact: true }).fill(asOf);
    await queried(page, '/api/shares/history', { frequency, group: groupName, start, end: asOf }, () => page.getByRole('button', { name: '查询历史', exact: true }).click());
    const title = `历史${periodNames[frequency]}份额（亿份）`; const lines = await chartLines(page, title);
    expect(lines).toHaveLength(3); expect(lines[0]).toEqual({ name: `510300 ${product.name}`, data: [1, null, 1.2], connectNulls: false }); expect(lines[2].data).toEqual([null, null, null]);
    await expect(panel(page, '份额历史明细')).not.toContainText('契约国债ETF');
    // 修改但不提交草稿：下载必须仍对应已返回查询，不能偷用未提交代码或服务端全量导出。
    await page.getByLabel('ETF 代码', { exact: true }).fill('511010');
    const jsonPending = page.waitForEvent('download'); await page.getByRole('button', { name: '导出 JSON', exact: true }).click(); const jsonDownload = await jsonPending;
    expect(jsonDownload.suggestedFilename()).toBe(`ETF-份额历史-${frequency}.json`);
    const json = JSON.parse((await downloaded(jsonDownload)).toString('utf8'));
    expect(json).toMatchObject({ mode: 'demo', frequency, notice, filters: { frequency, group: groupName, start, end: asOf, code: '' } });
    expect(json.items).toHaveLength(9); expect(json.items.every((item: { group: string }) => item.group === groupName)).toBe(true); expect(json.items[1].total_shares).toBeNull();
    expect(json.items[6].delta_shares).toBeNull(); expect(json.items[6].comparable_count).toBeNull(); expect(json.items[0]).not.toHaveProperty('estimated_flow'); expect(json.items[0]).not.toHaveProperty('nav'); expect(json.items[0]).not.toHaveProperty('score');
    const csvPending = page.waitForEvent('download'); await page.getByRole('button', { name: '导出 CSV', exact: true }).click(); const csvDownload = await csvPending;
    expect(csvDownload.suggestedFilename()).toBe(`ETF-份额历史-${frequency}.csv`); const csv = (await downloaded(csvDownload)).toString('utf8');
    expect(csv).toContain('"# frequency","' + frequency + '"'); expect(csv).toContain('"510300"'); expect(csv).toContain('"120000000"'); expect(csv).not.toContain('511010'); expect(csv).not.toContain('estimated_flow');
    const emptyRow = csv.split('\r\n').find(row => row.includes('"510330"'))!; expect(emptyRow).toBeTruthy(); expect(emptyRow).toContain('"","","","",');
    await pngDownload(page, title);
    await page.getByLabel('ETF 代码', { exact: true }).fill('510300');
    await queried(page, '/api/shares/history', { frequency, group: groupName, code: '510300', start, end: asOf }, () => page.getByRole('button', { name: '查询历史', exact: true }).click());
    await expect.poll(async () => (await chartLines(page, title)).length).toBe(1);
    await expect(panel(page, '份额历史明细').getByRole('row')).toHaveCount(4);
    expect(mock.requests.some(item => ['/api/export', '/api/shares/export', '/api/history', '/api/dashboard'].includes(item.path))).toBe(false); expect(mock.unexpected).toEqual([]);
  });
}

test('份额契约：目录筛选、人工证据确认与有状态重读，catalogue/shares 任务严格带 token', async ({ page }) => {
  const mock = await sharesContract(page); await page.goto('/#/catalogue'); await expect(page.getByRole('heading', { name: 'ETF 发现目录', exact: true })).toBeVisible();
  await expect(page.getByText('API 模式：演示（固定样例，非真实市场）', { exact: true })).toBeVisible();
  await page.getByText('目录覆盖 / 来源（API 返回）', { exact: true }).click(); await expect(page.locator('details pre')).toContainText(candidate.catalogue_source);
  await page.getByRole('combobox', { name: '资产类', exact: true }).selectOption('宽基'); await page.getByLabel('分组', { exact: true }).fill(groupName); await page.getByRole('combobox', { name: '分类状态', exact: true }).selectOption('candidate'); await page.getByLabel('检索', { exact: true }).fill('契约候选');
  await queried(page, '/api/catalogue', { asset_class: '宽基', group: groupName, classification_status: 'candidate', q: '契约候选', limit: '100', offset: '0' }, () => page.getByRole('button', { name: '查询目录', exact: true }).click());
  const row = page.getByRole('row').filter({ hasText: candidate.code }); await expect(row).toContainText('候选待核验'); await expect(row).toContainText('候选 / 未分类不视为已确认同指数成员');
  await row.getByRole('button', { name: '人工确认', exact: true }).click(); await page.getByLabel('确认分组', { exact: true }).fill(groupName); await page.getByRole('combobox', { name: '确认资产类', exact: true }).selectOption('宽基'); await page.getByLabel('跟踪指数', { exact: true }).fill('沪深300指数');
  await page.getByRole('button', { name: '保存人工确认', exact: true }).click(); await expect(page.getByText('请先核对真实来源及跟踪指数，确认候选证据不是最终分类', { exact: true })).toBeVisible(); expect(mock.requests.filter(item => item.method === 'POST')).toHaveLength(0);
  await page.getByLabel('已核验来源、资产类与分组；候选规则不作为确认依据', { exact: true }).check(); await page.getByRole('button', { name: '保存人工确认', exact: true }).click();
  await expect(page.getByText('人工分类已保存；不改变独立观察池', { exact: true })).toBeVisible(); await expect(page.getByText('当前筛选无目录产品。可同步发现目录并检查任务结果，不用观察池冒充完整目录。', { exact: true })).toBeVisible();
  const classification = mock.requests.find(item => item.path === '/api/catalogue/classify'); expect(classification).toMatchObject({ method: 'POST', token, body: { code: candidate.code, group: groupName, asset_class: '宽基', tracking_index: '沪深300指数', classification_status: 'confirmed' } }); expect(Object.keys(classification!.body!).sort()).toEqual(['asset_class', 'classification_status', 'code', 'group', 'tracking_index']);
  await page.getByRole('combobox', { name: '分类状态', exact: true }).selectOption('confirmed'); await page.getByRole('button', { name: '查询目录', exact: true }).click(); await expect(row).toContainText('人工确认'); await expect(row).toContainText('沪深300指数');
  // 采集仅使用已提交资产类与分组，不携带关键词、候选状态、分页或尚未提交草稿。
  await page.getByLabel('分组', { exact: true }).fill('未提交组'); await page.getByRole('button', { name: '同步发现目录', exact: true }).click(); await expect(page.getByText('shares-task-1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '更新日份额', exact: true }).click(); await expect(page.getByText('shares-task-2', { exact: true })).toBeVisible(); await expect(panel(page, '本页提交任务')).toContainText('服务返回：queued');
  expect(mock.requests.filter(item => item.path === '/api/tasks' && item.method === 'POST').map(item => ({ body: item.body, token: item.token }))).toEqual([{ body: { kind: 'catalogue' }, token }, { body: { kind: 'shares', group: groupName, asset_class: '宽基' }, token }]); expect(mock.requests.filter(item => item.path === '/api/session')).toHaveLength(1); expect(mock.unexpected).toEqual([]);
});

test('份额契约：任务失败与100%进度不假报采集成功，403不触发状态变更', async ({ page }) => {
  const mock = await sharesContract(page, { failedTask: true }); await page.goto('/#/catalogue'); await page.getByRole('button', { name: '同步发现目录', exact: true }).click();
  await expect(panel(page, '本页提交任务')).toContainText('服务返回：failed'); await expect(panel(page, '本页提交任务')).toContainText('交易所目录采集失败'); await expect(panel(page, '本页提交任务')).toContainText('目录来源请求失败，没有有效记录');
  mock.failures.set('/api/tasks', { status: 403, detail: '份额契约会话令牌无效' }); await page.getByRole('button', { name: '更新日份额', exact: true }).click(); await expect(page.getByText('份额契约会话令牌无效', { exact: true })).toBeVisible(); expect(mock.tasks).toHaveLength(1); expect(mock.unexpected).toEqual([]);
});

const emptyPages = [
  { route: 'dashboard', heading: '份额总览', text: '当前范围没有已确认分组；请同步目录、核验分类并更新份额，不使用演示数据填补。' },
  { route: 'history', heading: '历史份额', text: '当前查询范围无份额历史；不使用虚拟记录或流量替代。' },
  { route: 'catalogue', heading: 'ETF 发现目录', text: '当前筛选无目录产品。可同步发现目录并检查任务结果，不用观察池冒充完整目录。' },
];
for (const scenario of emptyPages) {
  test(`份额契约：${scenario.heading}真实空库不补演示、不造零曲线`, async ({ page }) => {
    const mock = await sharesContract(page, { empty: true }); await page.goto(`/#/${scenario.route}`); await expect(page.getByRole('heading', { name: scenario.heading, exact: true })).toBeVisible(); await expect(page.getByTestId('mode-banner')).toContainText('真实数据模式');
    await expect(page.getByText(scenario.text, { exact: true })).toBeVisible(); await expect(page.getByText(/契约核心ETF|契约候选ETF/)).toHaveCount(0); await expect(page.getByRole('img')).toHaveCount(0);
    for (const button of await page.getByRole('button', { name: '导出 PNG', exact: true }).all()) await expect(button).toBeDisabled();
    if (scenario.route === 'dashboard') await expect(page.locator('.metric').filter({ hasText: '同日总份额（亿份）' }).locator('strong')).toHaveText('—'); expect(mock.unexpected).toEqual([]);
  });
}

for (const scenario of [
  { route: 'dashboard', path: '/api/shares/overview', text: '份额总览接口不存在（404）' },
  { route: 'history', path: '/api/shares/history', text: '份额历史接口不存在（404）' },
  { route: 'catalogue', path: '/api/catalogue', text: '目录接口不存在（404）' },
  { route: `groups/${encodeURIComponent(groupName)}`, path: `/api/shares/groups/${encodeURIComponent(groupName)}`, text: '分组份额接口不存在（404）' },
]) {
  test(`份额契约：${scenario.path}返回404显式错误、禁止误导下载、重试恢复`, async ({ page }) => {
    const mock = await sharesContract(page); mock.failures.set(scenario.path, { status: 404, detail: scenario.text }); const downloads: Download[] = []; page.on('download', download => downloads.push(download));
    await page.goto(`/#/${scenario.route}`); await expect(page.getByText('读取失败', { exact: true })).toBeVisible(); await expect(page.getByText(scenario.text, { exact: true })).toHaveCount(2); await expect(page.getByRole('img')).toHaveCount(0);
    if (scenario.route === 'history') { await expect(page.getByRole('button', { name: '导出 CSV', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: '导出 JSON', exact: true })).toBeDisabled(); await expect(page.getByRole('button', { name: '导出 PNG', exact: true })).toBeDisabled(); }
    expect(downloads).toEqual([]); mock.failures.delete(scenario.path); await page.getByRole('button', { name: '重试', exact: true }).click(); await expect(page.getByText('读取失败', { exact: true })).toHaveCount(0); expect(mock.unexpected).toEqual([]);
  });
}

test('份额契约：接口模式未知不借用健康live认证，覆盖缺数仍为横线', async ({ page }) => {
  const mock = await sharesContract(page, { mode: 'live', unknownMode: true, unknownCoverage: true }); await page.goto('/#/dashboard');
  await expect(page.getByTestId('mode-banner')).toContainText('真实数据模式'); await expect(page.getByText('份额接口 · 模式未知，不认定为真实有效', { exact: true })).toBeVisible();
  const row = page.getByRole('row').filter({ has: page.getByRole('link', { name: groupName, exact: true }) });
  await expect(row).toContainText('同日可用 —/— · 可比 — · 可比覆盖 —'); await expect(row).toContainText('分类候选 — · 缺失 —');
  await expect(page.locator('.metric').filter({ hasText: '同日覆盖 / 可比 / 已确认成员' }).locator('strong')).toHaveText('— / — / —'); expect(mock.unexpected).toEqual([]);
});
