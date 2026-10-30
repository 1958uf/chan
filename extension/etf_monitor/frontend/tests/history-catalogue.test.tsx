import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { EChartsOption } from 'echarts';
import App from '../src/App';
import { api } from '../src/api/client';
import type { CatalogueResponse, ETF, ShareGroupSummary, ShareHistoryItem, SharesHistory, SharesOverview, Task } from '../src/api/types';
import { CataloguePage } from '../src/pages/Catalogue';
import { HistoryPage, LegacyHistoryPage, sharesHistoryBlob, sharesHistoryChart } from '../src/pages/History';
import { ToastProvider } from '../src/ui';
import { health } from './fixtures';

// 功能：替代组件测试中的 canvas，保留配置以校验期末存量；输入：图表属性；输出：可读取的固定图表配置。
vi.mock('../src/components/Chart', () => ({ Chart: ({ title, option, hasData }: { title: string; option: EChartsOption; hasData: boolean }) => <section aria-label={title}><h2>{title}</h2><button disabled={!hasData}>导出 PNG</button><pre data-testid="history-chart-option">{JSON.stringify(option)}</pre>{!hasData && <p>当前范围没有可绘制数据；缺失不等于零。</p>}</section> }));

// 以下固定样例仅用于测试：分组不来自精选观察池，周/月数值均为期末存量。
const group: ShareGroupSummary = { group: '完整目录指数', asset_class: '宽基', total_shares: 200000000, delta_shares: 10000000, delta_pct: 5.26, increased: 1, decreased: 0, unchanged: 0, missing_count: 1, candidate_count: 1, total_count: 2, available_count: 1, comparable_count: 1, coverage_pct: 50, trade_date: '2026-10-30', quality: 'partial' };
const overview: SharesOverview = { mode: 'demo', as_of: '2026-10-30', period: 'day', items: [], groups: [group], coverage: { total_count: 2, comparable_count: 1 }, notice: '固定目录分组样例' };
const row: ShareHistoryItem = { date: '2026-10-23', group: group.group, total_shares: 100000000, delta_shares: 5000000, delta_pct: 5.26, comparable_count: 1, total_count: 2, coverage_pct: 50, quality: 'partial' };
const history: SharesHistory = { mode: 'demo', frequency: 'day', notice: '固定份额历史口径；不是流量', items: [row, { ...row, date: '2026-10-30', total_shares: 200000000 }, { ...row, group: '另一指数', total_shares: 300000000 }] };
const candidate: ETF = { code: '510999', name: '候选产品ETF', exchange: 'sh', group: '未分类', enabled: true, tags: ['候选'], asset_class: '未分类', tracking_index: null, classification_status: 'candidate', classification_evidence: '仅名称候选：指数变体尚未核验', catalogue_source: '测试交易所目录', discovered_at: '2026-10-30T16:00:00+08:00', manual_classification: false };
const catalogue: CatalogueResponse = { mode: 'demo', items: [candidate, { ...candidate, code: '159999', name: '未分类产品ETF', exchange: 'sz', classification_status: 'unclassified', classification_evidence: '' }], total: 205, coverage: { sources: { '测试交易所目录': 205 }, candidate: 1, unclassified: 1 }, notice: '固定目录：候选需人工核验' };
const task: Task = { id: 'catalogue-task-1', kind: 'catalogue', status: 'queued', progress: 0, created_at: '2026-10-30T16:00:00+08:00', message: '后台排队' };

/** 功能：给页面提供真实通知组件；输入：页面节点；输出：测试渲染结果。 */
function view(node: React.ReactNode) { return render(<ToastProvider>{node}</ToastProvider>); }
/** 功能：读取浏览器 Blob（兼容 jsdom）；输入：下载文件；输出：UTF-8 文本。 */
function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsText(blob); });
}
/** 功能：固定页面的份额和目录响应；输入：无；输出：接口监视器，不调用真实后端。 */
function mockShares() { return { overview: vi.spyOn(api, 'sharesOverview').mockResolvedValue(overview), history: vi.spyOn(api, 'sharesHistory').mockResolvedValue(history), catalogue: vi.spyOn(api, 'catalogue').mockResolvedValue(catalogue) }; }

 describe('纯份额历史', () => {
  it('仅使用 shares 接口，分组取 overview.groups 而非观察池，显示模式、口径和质量', async () => {
    const mocks = mockShares(); const etfs = vi.spyOn(api, 'etfs'); const legacy = vi.spyOn(api, 'history');
    view(<HistoryPage />);
    await screen.findByText(history.notice);
    expect(mocks.history).toHaveBeenCalledWith({ start: '', end: '', frequency: 'day', group: '', code: '' });
    expect(screen.getByLabelText('指数分组')).toHaveTextContent(group.group); expect(etfs).not.toHaveBeenCalled(); expect(legacy).not.toHaveBeenCalled();
    expect(screen.getByText(/API 模式：演示/)).toBeVisible();
    expect(screen.getAllByText('部分缺失')[0]).not.toHaveClass('good');
    expect(screen.getByRole('columnheader', { name: '可比 / 总数' })).toBeVisible(); expect(screen.getByRole('columnheader', { name: '可比覆盖（%）' })).toBeVisible();
    expect(screen.queryByRole('columnheader', { name: /净值|估算流量|评分/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '旧版估算流量（验证辅助）' })).toHaveAttribute('href', '#/legacy-history');
    expect(screen.getByRole('link', { name: 'ETF 发现目录' })).toHaveAttribute('href', '#/catalogue');
  });
  it('day/week/month 查询携带 start/end/frequency/group/code，周月直接绘期末不日 sum', async () => {
    const mocks = mockShares(); mocks.history.mockImplementation(async filters => ({ ...history, frequency: filters?.frequency || 'day' }));
    view(<HistoryPage />); await screen.findByText(history.notice);
    await userEvent.type(screen.getByLabelText('开始日期'), '2026-10-01'); await userEvent.type(screen.getByLabelText('结束日期'), '2026-10-30');
    await userEvent.selectOptions(screen.getByLabelText('指数分组'), group.group); await userEvent.type(screen.getByLabelText('ETF 代码'), '510999');
    for (const frequency of ['week', 'month', 'day'] as const) {
      await userEvent.selectOptions(screen.getByLabelText('频率'), frequency); await userEvent.click(screen.getByRole('button', { name: '查询历史' }));
      await waitFor(() => expect(mocks.history).toHaveBeenLastCalledWith({ start: '2026-10-01', end: '2026-10-30', frequency, group: group.group, code: '510999' }));
      await waitFor(() => expect(screen.getByRole('button', { name: '导出 JSON' })).toBeEnabled());
      const option = JSON.parse(screen.getByTestId('history-chart-option').textContent!);
      expect(option.series.map((line: { data: unknown }) => line.data)).toEqual([[1, 2], [3, null]]);
      expect(option.yAxis.name).toBe('亿份'); expect(option.series[0].connectNulls).toBe(false);
    }
  });
  it('多产品独立绘线，显式 shares:null 不用 total_shares 补零或补值', () => {
    const option = sharesHistoryChart([{ ...row, code: '510999', shares: 500000000 }, { ...row, code: '159999', shares: null, total_shares: 100000000 }, { ...row, date: '2026-10-30', code: '510999', shares: 600000000 }]) as { series: { data: unknown[]; name: string }[] };
    expect(option.series.map(line => line.data)).toEqual([[5, 6], [null, null]]); expect(option.series[0].name).toContain('510999');
  });
  it('缺份额、变化、可比数与覆盖显示横线，PNG 无数据不可导出', async () => {
    const mocks = mockShares(); mocks.history.mockResolvedValue({ ...history, mode: 'unknown', frequency: 'unknown', items: [{ ...row, total_shares: null, delta_shares: null, delta_pct: null, comparable_count: null, coverage_pct: null, quality: 'missing' }] });
    view(<HistoryPage />); await screen.findByText(history.notice);
    expect(screen.getByText(/API 模式：未知/)).toBeVisible(); expect(screen.getByText('缺失')).not.toHaveClass('good');
    expect(screen.getByRole('button', { name: '导出 PNG' })).toBeDisabled(); expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText('— / 2')).toBeVisible();
  });
  it('JSON/CSV 下载本地当前查询快照，携带 metadata/filters 并排除 NAV/score，不调用 overview export', async () => {
    const mocks = mockShares(); const leaked = { ...row, nav: 4, price: 5, score: 90, estimated_flow: 123 };
    mocks.history.mockResolvedValue({ ...history, items: [leaked] });
    const serverExport = vi.spyOn(api, 'exportShares'); const legacyExport = vi.spyOn(api, 'exportData');
    const blobs: Blob[] = []; vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => { blobs.push(blob as Blob); return 'blob:fixed-fixture'; });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    view(<HistoryPage />); await screen.findByText(history.notice);
    // 草稿尚未提交：导出仍绑定成功返回时的筛选，不误标为当前输入。
    await userEvent.type(screen.getByLabelText('ETF 代码'), '510999'); await userEvent.selectOptions(screen.getByLabelText('频率'), 'week');
    await userEvent.click(screen.getByRole('button', { name: '导出 JSON' }));
    const payload = JSON.parse(await blobText(blobs[0]));
    expect(payload).toMatchObject({ mode: 'demo', frequency: 'day', notice: history.notice, filters: { code: '', frequency: 'day', start: '', end: '', group: '' }, items: [row] });
    expect(payload.items[0]).not.toHaveProperty('nav'); expect(payload.items[0]).not.toHaveProperty('estimated_flow'); expect(payload.items[0]).not.toHaveProperty('score'); expect(payload.items[0]).not.toHaveProperty('price');
    await userEvent.click(screen.getByRole('button', { name: '导出 CSV' })); const csv = await blobText(blobs[1]);
    expect(csv).toContain('"# mode","demo"'); expect(csv).toContain('"# frequency","day"'); expect(csv).toContain('"# filters"'); expect(csv).toContain('"total_shares"'); expect(csv).not.toContain('estimated_flow');
    expect(serverExport).not.toHaveBeenCalled(); expect(legacyExport).not.toHaveBeenCalled();
  });
  it('CSV 正确转义中文、换行、引号，文本公式加前缀，缺值不写成零', async () => {
    const data: SharesHistory = { ...history, items: [{ ...row, group: '=SUM(1,2)', reason: '中文,"证据"\n换行', total_shares: null, delta_shares: -5000000 }] };
    const csv = await blobText(sharesHistoryBlob(data, { start: '', end: '', group: '', code: '', frequency: 'week' }, 'csv'));
    expect(csv).toContain('"\'=SUM(1,2)"'); expect(csv).toContain('"中文,""证据""\n换行"'); expect(csv).toContain('"-5000000"');
    const json = JSON.parse(await blobText(sharesHistoryBlob(data, { start: '', end: '', group: '', code: '', frequency: 'week' }, 'json')));
    expect(json.items[0].total_shares).toBeNull(); expect(json.items[0].group).toBe('=SUM(1,2)');
  });
  it('API 失败、日期倒置和非法代码显式报错，失败查询不导出空文件', async () => {
    const mocks = mockShares(); mocks.history.mockRejectedValue(new Error('份额历史服务不可用'));
    view(<HistoryPage />); expect(await screen.findByText('读取失败')).toBeVisible(); expect(screen.getByRole('button', { name: '导出 JSON' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('开始日期'), '2026-10-30'); await userEvent.type(screen.getByLabelText('结束日期'), '2026-10-01'); await userEvent.click(screen.getByRole('button', { name: '查询历史' }));
    expect(await screen.findByText('开始日期不能晚于结束日期')).toBeVisible(); expect(mocks.history).toHaveBeenCalledTimes(1);
    await userEvent.clear(screen.getByLabelText('开始日期')); await userEvent.type(screen.getByLabelText('ETF 代码'), 'bad'); await userEvent.click(screen.getByRole('button', { name: '查询历史' }));
    expect(await screen.findByText('ETF 代码必须是六位数字')).toBeVisible(); expect(mocks.history).toHaveBeenCalledTimes(1);
  });
  it('旧历史验证页仍导出并使用旧 history，不取纯 shares', async () => {
    const old = vi.spyOn(api, 'history').mockResolvedValue({ items: [{ date: row.date, code: candidate.code, group: '旧观察池', shares: 100000000, estimated_flow: 10000000, quality: 'demo' }] });
    vi.spyOn(api, 'etfs').mockResolvedValue({ items: [{ ...candidate, group: '旧观察池' }] }); const pure = vi.spyOn(api, 'sharesHistory');
    view(<LegacyHistoryPage />); expect(await screen.findByText(candidate.code)).toBeVisible(); expect(old).toHaveBeenCalled(); expect(pure).not.toHaveBeenCalled(); expect(screen.getByRole('heading', { name: '历史资金流量' })).toBeVisible();
  });
});

describe('发现目录和人工确认', () => {
  it('目录 class/group/status/q 筛选与 100 条分页，观察池独立且候选证据可见', async () => {
    const mocks = mockShares(); const watchpool = vi.spyOn(api, 'etfs'); view(<CataloguePage />);
    await screen.findByText('仅名称候选：指数变体尚未核验');
    expect(mocks.catalogue).toHaveBeenCalledWith({ asset_class: '', group: '', classification_status: undefined, q: '', limit: 100, offset: 0 }); expect(watchpool).not.toHaveBeenCalled();
    expect(within(screen.getByRole('table')).getByText('候选待核验')).toBeVisible(); expect(screen.getAllByText('候选 / 未分类不视为已确认同指数成员')).toHaveLength(2);
    expect(screen.getByText(/发现目录与/)).toHaveTextContent('精选观察池独立'); expect(screen.getByText(/API 模式：演示/)).toBeVisible(); expect(screen.getByText(catalogue.notice!)).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '下一页' })); await waitFor(() => expect(mocks.catalogue).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 100, offset: 100 })));
    await userEvent.selectOptions(screen.getByLabelText('资产类'), '主题'); await userEvent.type(screen.getByLabelText('分组'), ' 精确指数 '); await userEvent.selectOptions(screen.getByLabelText('分类状态'), 'candidate'); await userEvent.type(screen.getByLabelText('检索'), ' 候选 ');
    await userEvent.click(screen.getByRole('button', { name: '查询目录' })); await waitFor(() => expect(mocks.catalogue).toHaveBeenLastCalledWith({ asset_class: '主题', group: '精确指数', classification_status: 'candidate', q: '候选', limit: 100, offset: 0 }));
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled();
  });
  it('人工确认只发送代码/组/资产类/跟踪指数/confirmed 白名单，须勾选证据核验', async () => {
    mockShares(); const classify = vi.spyOn(api, 'classifyETF').mockResolvedValue({ ...candidate, classification_status: 'confirmed' }); view(<CataloguePage />);
    await screen.findByText('仅名称候选：指数变体尚未核验'); await userEvent.click(screen.getAllByRole('button', { name: '人工确认' })[0]);
    expect(screen.getByLabelText('确认代码')).toHaveAttribute('readonly'); expect(within(screen.getByLabelText('确认资产类')).queryByRole('option', { name: '未分类' })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('确认分组'), '沪深300'); await userEvent.selectOptions(screen.getByLabelText('确认资产类'), '宽基'); await userEvent.type(screen.getByLabelText('跟踪指数'), '沪深300指数');
    await userEvent.click(screen.getByRole('button', { name: '保存人工确认' })); expect(await screen.findByText('请先核对真实来源及跟踪指数，确认候选证据不是最终分类')).toBeVisible(); expect(classify).not.toHaveBeenCalled();
    await userEvent.click(screen.getByLabelText('已核验来源、资产类与分组；候选规则不作为确认依据')); await userEvent.click(screen.getByRole('button', { name: '保存人工确认' }));
    await waitFor(() => expect(classify).toHaveBeenCalledWith({ code: '510999', group: '沪深300', asset_class: '宽基', tracking_index: '沪深300指数', classification_status: 'confirmed' }));
    expect(Object.keys(classify.mock.calls[0][0]).sort()).toEqual(['code', 'group', 'asset_class', 'tracking_index', 'classification_status'].sort());
    expect(await screen.findByText('人工分类已保存；不改变独立观察池')).toBeVisible(); expect(screen.queryByLabelText('确认代码')).not.toBeInTheDocument();
  });
  it('人工分类分组40字可提交，41字在前端拒绝且不发请求', async () => {
    mockShares(); const classify = vi.spyOn(api, 'classifyETF').mockResolvedValue({ ...candidate, classification_status: 'confirmed' }); view(<CataloguePage />);
    await screen.findByText('仅名称候选：指数变体尚未核验'); await userEvent.click(screen.getAllByRole('button', { name: '人工确认' })[0]);
    const input = screen.getByLabelText('确认分组'); expect(input).toHaveAttribute('maxlength', '40');
    await userEvent.selectOptions(screen.getByLabelText('确认资产类'), '宽基'); await userEvent.click(screen.getByLabelText('已核验来源、资产类与分组；候选规则不作为确认依据'));
    // 绕过浏览器输入长度限制，验证提交逻辑本身同样拒绝超长分组。
    fireEvent.change(input, { target: { value: '组'.repeat(41) } }); await userEvent.click(screen.getByRole('button', { name: '保存人工确认' }));
    expect(await screen.findByText(/有效分组（1–40 字）/)).toBeVisible(); expect(classify).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: '组'.repeat(40) } }); await userEvent.click(screen.getByRole('button', { name: '保存人工确认' }));
    await waitFor(() => expect(classify).toHaveBeenCalledWith({ code: candidate.code, group: '组'.repeat(40), asset_class: '宽基', tracking_index: undefined, classification_status: 'confirmed' }));
  });
  it('未核验资产类/空分组不提交，分类保存失败保留表单不假成功', async () => {
    mockShares(); const classify = vi.spyOn(api, 'classifyETF').mockRejectedValue(new Error('分类写入失败')); view(<CataloguePage />);
    await screen.findByText('仅名称候选：指数变体尚未核验'); await userEvent.click(screen.getAllByRole('button', { name: '人工确认' })[0]); await userEvent.click(screen.getByRole('button', { name: '保存人工确认' }));
    expect(await screen.findByText(/请填写有效分组/)).toBeVisible(); expect(classify).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText('确认分组'), '新主题'); await userEvent.selectOptions(screen.getByLabelText('确认资产类'), '主题'); await userEvent.click(screen.getByLabelText('已核验来源、资产类与分组；候选规则不作为确认依据')); await userEvent.click(screen.getByRole('button', { name: '保存人工确认' }));
    expect(await screen.findByText('分类写入失败')).toBeVisible(); expect(screen.getByLabelText('确认代码')).toBeVisible(); expect(screen.queryByText('人工分类已保存；不改变独立观察池')).not.toBeInTheDocument();
  });
  it('目录同步 kind catalogue；份额更新 kind shares 按提交范围；任务失败与部分错误真实显示', async () => {
    mockShares(); const create = vi.spyOn(api, 'createTask').mockResolvedValueOnce(task).mockResolvedValue({ ...task, id: 'shares-task-1', kind: 'shares' });
    vi.spyOn(api, 'tasks').mockResolvedValue({ items: [{ ...task, status: 'failed', progress: 100, message: '目录同步失败', errors: ['交易所目录请求超时'] }, { ...task, id: 'shares-task-1', kind: 'shares', status: 'failed', progress: 100, message: '份额更新部分失败', errors: ['深市份额请求失败'] }] });
    view(<CataloguePage />); await screen.findByText('仅名称候选：指数变体尚未核验');
    await userEvent.selectOptions(screen.getByLabelText('资产类'), '宽基'); await userEvent.type(screen.getByLabelText('分组'), group.group); await userEvent.click(screen.getByRole('button', { name: '查询目录' }));
    await userEvent.click(screen.getByRole('button', { name: '同步发现目录' })); expect(create).toHaveBeenNthCalledWith(1, { kind: 'catalogue' });
    expect(await screen.findByText('目录同步失败')).toBeVisible(); expect(screen.getByText('交易所目录请求超时')).toBeVisible(); expect(screen.queryByText('已完成')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '更新日份额' })); expect(create).toHaveBeenNthCalledWith(2, { kind: 'shares', group: group.group, asset_class: '宽基' });
    expect(await screen.findByText('份额更新部分失败')).toBeVisible(); expect(screen.getByText('深市份额请求失败')).toBeVisible(); expect(screen.getAllByText('失败')).toHaveLength(2);
    expect(screen.getAllByText('任务已受理，不代表采集成功；可能失败或部分成功，请核对后端状态').length).toBeGreaterThanOrEqual(1);
  });
  it('任务提交被拒明确错误，不显示受理或伪造完成；目录空/缺值不冒充完整', async () => {
    const mocks = mockShares(); mocks.catalogue.mockResolvedValue({ ...catalogue, mode: 'unknown', items: [], total: null, coverage: {} }); vi.spyOn(api, 'createTask').mockRejectedValue(new Error('任务提交失败'));
    view(<CataloguePage />); expect(await screen.findByText(/当前筛选无目录产品/)).toBeVisible(); expect(screen.getByText(/API 模式：未知/)).toBeVisible(); expect(screen.getByText('总计 — 条')).toBeVisible(); expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '同步发现目录' })); expect(await screen.findByText('任务提交失败')).toBeVisible(); expect(screen.queryByRole('heading', { name: '本页提交任务' })).not.toBeInTheDocument(); expect(screen.queryByText('已完成')).not.toBeInTheDocument();
  });
  it('应用 hash 路由连接 history/catalogue/legacy-history，旧验证辅助可导航', async () => {
    mockShares(); vi.spyOn(api, 'health').mockResolvedValue(health); vi.spyOn(api, 'etfs').mockResolvedValue({ items: [] }); vi.spyOn(api, 'history').mockResolvedValue({ items: [] });
    window.location.hash = '#/history'; render(<App />); expect(await screen.findByRole('heading', { name: '历史份额' })).toBeVisible();
    await userEvent.click(screen.getByRole('link', { name: 'ETF 发现目录' })); expect(await screen.findByRole('heading', { name: 'ETF 发现目录' })).toBeVisible(); expect(window.location.hash).toBe('#/catalogue');
    await userEvent.click(screen.getByRole('link', { name: '查询纯份额历史' })); expect(await screen.findByRole('heading', { name: '历史份额' })).toBeVisible();
    await userEvent.click(screen.getByRole('link', { name: '旧版估算流量（验证辅助）' })); expect(await screen.findByRole('heading', { name: '历史资金流量' })).toBeVisible(); expect(window.location.hash).toBe('#/legacy-history');
  });
});
