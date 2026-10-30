import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { api } from '../src/api/client';
import { LegacyDashboardPage, ETFPage, GroupCoverage, latestMarketRecords } from '../src/pages/Dashboard';
import { DetailPage, HolderTable, serviceTradeDate } from '../src/pages/Detail';
import { AlertsPage, HealthPage, taskProgress, TasksPage } from '../src/pages/Operations';
import { SettingsPage, WatchlistPage } from '../src/pages/Management';
import { Badge, billion, number, ToastProvider } from '../src/ui';
import { dashboard, detail, etf, health, holder, settings, task } from './fixtures';

// 组件层仅替代 canvas 图表；图表真实渲染由浏览器测试执行。
vi.mock('../src/components/Chart', () => ({ Chart: ({ title, hasData }: { title: string; hasData: boolean }) => <section aria-label={title}>{title}{!hasData && <p>当前范围没有可绘制数据；缺失不等于零。</p>}</section> }));
/** 功能：给被测页面提供统一通知；输入：页面节点；输出：渲染结果。 */
function view(node: React.ReactNode) { return render(<ToastProvider>{node}</ToastProvider>); }

describe('中文页面与空失败状态', () => {
  it('缺数字显示横线，数据不足与 demo 不显示绿色正常', () => {
    expect(number(null)).toBe('—'); expect(billion(undefined)).toBe('—');
    view(<><Badge value="unknown" /><Badge value="demo" /><Badge value="partial" /></>);
    expect(screen.getByText('未知')).not.toHaveClass('good'); expect(screen.getByText('演示')).not.toHaveClass('good'); expect(screen.getByText('部分缺失')).not.toHaveClass('good');
  });
  it('仪表盘保留份额日期、行情时间并声明评分非概率', async () => {
    vi.spyOn(api, 'dashboard').mockResolvedValue(dashboard); const onDetail = vi.fn();
    view(<LegacyDashboardPage onDetail={onDetail} />);
    expect(await screen.findByText('沪深300ETF')).toBeVisible();
    expect(screen.getByText('份额日期 2026-10-28')).toBeVisible();
    expect(screen.getByText('评分是证据强度，不是上涨概率')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '沪深300ETF' })); expect(onDetail).toHaveBeenCalledWith('510300');
  });
  it('分组展示覆盖样本，不从覆盖完整推断绿色质量', () => {
    view(<><GroupCoverage group={{ group: '沪深300', flow: 8834000, count: 4, coverage: 4 }} /><GroupCoverage group={{ group: '部分', flow: 1, count: 3, coverage: 1 }} /><GroupCoverage group={{ group: '未知', flow: null, count: 2 }} /></>);
    expect(screen.getByText('样本 4/4')).toHaveClass('neutral'); expect(screen.getByText('样本 4/4')).not.toHaveClass('good');
    expect(screen.getByText('样本 1/3')).toHaveClass('warn'); expect(screen.getByText('样本未提供')).toBeVisible();
  });
  it('市场只显示每指标最新日期，不重复历史卡，乱序也能选最新', async () => {
    const meta = { source: '最新源', fetched_at: health.now, quality: 'demo' as const };
    const records = [
      { ...meta, trade_date: '2026-10-29', metric: 'turnover' as const, value: 220000000 },
      { ...meta, trade_date: '2026-10-28', metric: 'margin' as const, value: 330000000 },
      { ...meta, source: '旧源', trade_date: '2026-10-27', metric: 'turnover' as const, value: 110000000 },
      { ...meta, source: '旧源', trade_date: '2026-10-27', metric: 'margin' as const, value: 110000000 },
    ];
    expect(latestMarketRecords(records).map(item => item.value)).toEqual([220000000, 330000000]);
    vi.spyOn(api, 'dashboard').mockResolvedValue({ ...dashboard, market: records }); view(<LegacyDashboardPage onDetail={vi.fn()} />);
    const heading = await screen.findByRole('heading', { name: '市场背景 · 各指标最新日度记录' });
    const market = within(heading.closest('section')!); expect(market.getByText('成交额')).toBeVisible(); expect(market.getByText('融资余额')).toBeVisible();
    expect(market.getByText('2.20 亿元')).toBeVisible(); expect(market.getByText('3.30 亿元')).toBeVisible(); expect(market.queryByText(/旧源/)).not.toBeInTheDocument();
  });
  it('demo 后端返回 ok 时仅展示演示服务状态，不显示正常结论', async () => {
    vi.spyOn(api, 'health').mockResolvedValue({ ...health, status: 'ok', sources: [{ source: 'demo采集源', status: 'ok', last_success: health.now, checked_at: health.now }] }); view(<HealthPage />);
    expect(await screen.findAllByText('演示')).toHaveLength(2); expect(screen.queryByText('正常')).not.toBeInTheDocument(); expect(screen.getByText(/服务状态不等于数据质量/)).toBeVisible();
  });
  it('真实空库明确提示，不生成演示 ETF', async () => {
    vi.spyOn(api, 'dashboard').mockResolvedValue({ ...dashboard, mode: 'live', etfs: [], groups: [] }); view(<LegacyDashboardPage onDetail={vi.fn()} />);
    expect(await screen.findByText('分组数据为空，请检查观察池与采集任务。')).toBeVisible(); expect(screen.queryByText('沪深300ETF')).not.toBeInTheDocument();
  });
  it('API 失败同时显示页面错误和失败 toast，重试可恢复', async () => {
    vi.spyOn(api, 'etfs').mockRejectedValueOnce(new Error('后端连接失败')).mockResolvedValue({ items: [etf] }); view(<ETFPage onDetail={vi.fn()} />);
    expect(await screen.findByText('读取失败')).toBeVisible(); expect(screen.getAllByText('后端连接失败')).toHaveLength(2);
    await userEvent.click(screen.getByRole('button', { name: '重试' })); expect(await screen.findByText('沪深300ETF')).toBeVisible();
  });
  it('搜索及停用筛选具有明确空状态', async () => {
    vi.spyOn(api, 'etfs').mockResolvedValue({ items: [etf] }); view(<ETFPage onDetail={vi.fn()} />);
    await screen.findByText('沪深300ETF'); await userEvent.type(screen.getByLabelText('搜索 ETF'), '不存在');
    expect(screen.getByText('没有符合筛选的 ETF，请调整搜索条件。')).toBeVisible();
    await userEvent.clear(screen.getByLabelText('搜索 ETF')); await userEvent.selectOptions(screen.getByLabelText('观察状态'), 'false');
    expect(screen.queryByText('沪深300ETF')).not.toBeInTheDocument();
  });
  it('分钟无数据不拿日线填补，详情份额和行情分离', async () => {
    vi.spyOn(api, 'detail').mockResolvedValue(detail); view(<DetailPage code="510300" onBack={vi.fn()} />);
    await screen.findByRole('heading', { name: /沪深300ETF/ });
    expect(screen.getByRole('heading', { name: /行情快照/ })).toBeVisible(); expect(screen.getByRole('heading', { name: /交易所日份额/ })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '1分钟' }));
    expect(screen.getByText('当前范围没有可绘制数据；缺失不等于零。')).toBeVisible(); expect(screen.getByLabelText('1分钟行情')).toBeVisible();
  });
  it('分钟采集取实际 health 中国日期和周期，任务失败可见不补假图', async () => {
    expect(serviceTradeDate('2025-03-28T20:00:00Z')).toBe('2025-03-29'); expect(() => serviceTradeDate('invalid')).toThrow('后端健康时钟无效');
    vi.spyOn(api, 'detail').mockResolvedValue(detail); vi.spyOn(api, 'health').mockResolvedValue({ ...health, now: '2025-03-28T15:10:00+08:00' });
    const create = vi.spyOn(api, 'createTask').mockResolvedValue({ ...task, interval: '1m', start: '2025-03-28', end: '2025-03-28' });
    vi.spyOn(api, 'tasks').mockResolvedValue({ items: [{ ...task, status: 'failed', interval: '1m', message: '分钟源请求失败', errors: ['分钟数据不可用'] }] });
    view(<DetailPage code="510300" onBack={vi.fn()} />); await screen.findByRole('heading', { name: /沪深300ETF/ });
    expect(screen.queryByRole('button', { name: '采集分钟' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '1分钟' })); await userEvent.click(screen.getByRole('button', { name: '采集分钟' }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ kind: 'refresh', codes: ['510300'], start: '2025-03-28', end: '2025-03-28', interval: '1m' }));
    expect(await screen.findByText('分钟源请求失败')).toBeVisible(); expect(screen.getByText('分钟数据不可用')).toBeVisible(); expect(screen.getByText('失败')).toBeVisible(); expect(await screen.findByText('分钟采集失败：分钟源请求失败')).toBeVisible();
    expect(screen.getByText('当前范围没有可绘制数据；缺失不等于零。')).toBeVisible();
  });
  it('健康时钟读取失败时不提交分钟任务并提示错误', async () => {
    vi.spyOn(api, 'detail').mockResolvedValue(detail); vi.spyOn(api, 'health').mockRejectedValue(new Error('健康时钟无法连接')); const create = vi.spyOn(api, 'createTask');
    view(<DetailPage code="510300" onBack={vi.fn()} />); await screen.findByRole('heading', { name: /沪深300ETF/ }); await userEvent.click(screen.getByRole('button', { name: '5分钟' })); await userEvent.click(screen.getByRole('button', { name: '采集分钟' }));
    expect(await screen.findByText('健康时钟无法连接')).toBeVisible(); expect(create).not.toHaveBeenCalled();
  });
  it('后端日线参考价不能冒充实时行情快照', async () => {
    vi.spyOn(api, 'detail').mockResolvedValue({ ...detail, analysis: { ...detail.analysis, quote_time: null, price_time: '2026-10-28T15:00:00+08:00' }, quotes: [] });
    view(<DetailPage code="510300" onBack={vi.fn()} />);
    expect(await screen.findByText(/仅有历史日线参考价 4.000 元/)).toBeVisible();
    const heading = screen.getByRole('heading', { name: /行情快照/ });
    expect(within(heading.closest('section')!).getByText('—')).toBeVisible();
    expect(screen.getByText('无行情记录，不能判断当前价格。')).toBeVisible();
  });
  it('详情独立显示盘中估算与行情时差，不改变日评分', async () => {
    vi.spyOn(api, 'detail').mockResolvedValue({ ...detail, analysis: { ...detail.analysis, quote_age_seconds: 30, intraday_indicators: [{ name: '盘中量价线索（估算）', value: 1.23, state: 'unknown', quality: 'partial', direction_pct: 0.5, explanation: '线性交易进度，非同时间历史基线' }] } });
    view(<DetailPage code="510300" onBack={vi.fn()} />);
    const heading = await screen.findByRole('heading', { name: '盘中辅助线索 · 估算' }); const panel = within(heading.closest('section')!);
    expect(panel.getByText('盘中量价线索（估算）')).toBeVisible(); expect(panel.getByText('1.23')).toBeVisible(); expect(panel.getByText('独立展示 · 不纳入日评分')).toBeVisible();
    expect(panel.getByText('部分缺失')).not.toHaveClass('good'); expect(panel.getByText('未知')).not.toHaveClass('good');
    expect(screen.getByText(/行情源时差：30 秒/)).toBeVisible(); expect(screen.getByText(/评分 40 · 覆盖 50%/)).toBeVisible(); expect(screen.getByText(/固定权重计算/)).toBeVisible();
  });
  it('旧接口没有盘中数组时明确空状态，行情年龄未知不归零', async () => {
    vi.spyOn(api, 'detail').mockResolvedValue(detail); view(<DetailPage code="510300" onBack={vi.fn()} />);
    expect(await screen.findByText('暂无可用盘中辅助指标。接口未提供、行情陈旧或历史证据不足均不显示正常，不用日指标替代。')).toBeVisible();
    expect(screen.getByText(/行情源时差：未知/)).toBeVisible();
  });
  it('报告公告日未知不用于历史时点判断，危险 URL 不变为链接', () => {
    view(<HolderTable items={[{ ...holder, source_url: 'javascript:alert(1)' }]} />);
    expect(screen.getByText('未知 · 不可用于时点判断')).toBeVisible(); expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
  it('空源健康不能认定正常', async () => {
    vi.spyOn(api, 'health').mockResolvedValue({ ...health, mode: 'live', status: 'ok', sources: [] }); view(<HealthPage />);
    expect(await screen.findByText('尚不能认定全部正常：演示、空源、陈旧或失败需要核验')).toBeVisible(); expect(screen.getByText(/没有数据源健康记录/)).toBeVisible(); expect(screen.queryByText('正常')).not.toBeInTheDocument(); expect(screen.getByText('缺失')).not.toHaveClass('good');
  });
  it('告警确认发请求后重新读取，确认非解除', async () => {
    const alert = { id: 1, code: etf.code, kind: 'shares', severity: 'warning', title: '份额变化', message: '超过阈值', created_at: health.now, acknowledged: false };
    vi.spyOn(api, 'alerts').mockResolvedValueOnce({ items: [alert] }).mockResolvedValue({ items: [{ ...alert, acknowledged: true }] }); const ack = vi.spyOn(api, 'acknowledge').mockResolvedValue({ ok: true }); view(<AlertsPage />);
    await userEvent.click(await screen.findByRole('button', { name: '确认告警' })); await waitFor(() => expect(ack).toHaveBeenCalledWith(1)); expect(await screen.findByText('告警已确认（确认不等于风险解除）')).toBeVisible();
  });
  it('任务刷新创建、取消以及百分比可见', async () => {
    vi.spyOn(api, 'tasks').mockResolvedValue({ items: [task] }); const create = vi.spyOn(api, 'createTask').mockResolvedValue(task); const cancel = vi.spyOn(api, 'cancelTask').mockResolvedValue({ ok: true }); view(<TasksPage />);
    expect(await screen.findByText('20%')).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText('任务类型'), 'refresh');
    await userEvent.click(screen.getByRole('button', { name: '创建任务' })); await waitFor(() => expect(create).toHaveBeenCalledWith({ kind: 'refresh' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '取消任务' })).toBeEnabled()); await userEvent.click(screen.getByRole('button', { name: '取消任务' })); expect(cancel).toHaveBeenCalledWith('task-1');
    expect(taskProgress(140)).toBe(100); expect(taskProgress(-5)).toBe(0); expect(taskProgress(NaN)).toBe(0);
  });
  it('观察池新增、停用仅传 ETF 契约字段', async () => {
    vi.spyOn(api, 'etfs').mockResolvedValue({ items: [etf] }); const save = vi.spyOn(api, 'saveETF').mockResolvedValue(etf); view(<WatchlistPage />);
    await screen.findByText('沪深300ETF'); await userEvent.click(screen.getByRole('button', { name: '停用' })); await waitFor(() => expect(save).toHaveBeenCalledWith({ ...etf, enabled: false }));
    await userEvent.type(screen.getByLabelText('六位代码'), '159915'); await userEvent.type(screen.getByLabelText('ETF 名称'), '创业板ETF'); await userEvent.type(screen.getByLabelText('指数分组'), '创业板');
    await userEvent.click(screen.getByRole('button', { name: '保存标的' })); await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ code: '159915', name: '创业板ETF', group: '创业板' })));
  });
  it('配置只传白名单，不含令牌、目录或模式', async () => {
    vi.spyOn(api, 'settings').mockResolvedValue({ ...settings, data_dir: 'secret', token: 'secret' }); const save = vi.spyOn(api, 'saveSettings').mockResolvedValue(settings); view(<SettingsPage />);
    await screen.findByLabelText('行情轮询间隔（秒）'); await userEvent.click(screen.getByRole('button', { name: '保存配置' })); await waitFor(() => expect(save).toHaveBeenCalled());
    const body = save.mock.calls[0][0]; expect(body).not.toHaveProperty('token'); expect(body).not.toHaveProperty('data_dir'); expect(body).not.toHaveProperty('mode'); expect(Object.keys(body).sort()).toEqual(['scheduler_enabled', 'quote_interval', 'alert_cooldown_seconds', 'shares_alert_pct'].sort());
  });
  it('全局演示横幅在每页显示，浏览器导航可恢复', async () => {
    window.location.hash = '/intraday';
    vi.spyOn(api, 'health').mockResolvedValue(health); vi.spyOn(api, 'dashboard').mockResolvedValue(dashboard); vi.spyOn(api, 'etfs').mockResolvedValue({ items: [etf] });
    render(<App />); expect(await screen.findByText('演示模式 · 固定 seed 样例，不代表真实市场')).toBeVisible();
    const nav = screen.getByRole('navigation', { name: '主导航' }); await userEvent.click(within(nav).getByRole('link', { name: /ETF 检索/ }));
    expect(await screen.findByRole('heading', { name: 'ETF 检索' })).toBeVisible(); expect(screen.getByTestId('mode-banner')).toHaveTextContent('演示模式');
  });
});
