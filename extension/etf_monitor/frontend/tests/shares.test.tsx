import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import type { ShareGroupSummary, ShareItem, SharesOverview } from '../src/api/types';
import App from '../src/App';
import { health } from './fixtures';
import { boundedHistoryStart, DashboardPage, GroupPage, rankShares, sameDayTotal, SharesCoverage } from '../src/pages/Shares';
import { ToastProvider } from '../src/ui';

// 固定份额契约数据只用于测试，不作为生产页面的兜底数据。
const member: ShareItem = { code: '510300', name: '沪深300ETF', group: '沪深300', asset_class: '宽基', shares: 120000000, trade_date: '2026-10-28', delta_shares: 2000000, delta_pct: 1.694915, delta_5d: null, delta_20d: null, increase_streak: 2, decrease_streak: 0, quality: 'demo', reason: '', source: '固定测试', classification_status: 'confirmed' };
const missing: ShareItem = { ...member, code: '510310', name: '缺失产品', shares: null, delta_shares: null, delta_pct: null, increase_streak: null, decrease_streak: null, quality: 'missing', reason: '同日份额缺失' };
const summary: ShareGroupSummary = { group: '沪深300', asset_class: '宽基', total_shares: 120000000, delta_shares: 2000000, delta_pct: 1.694915, increased: 1, decreased: 0, unchanged: 0, missing_count: 1, candidate_count: 1, total_count: 2, available_count: 1, comparable_count: 1, coverage_pct: 50, trade_date: '2026-10-28', quality: 'demo' };
const overview: SharesOverview = { as_of: '2026-10-28', items: [member, missing], groups: [summary], mode: 'demo', notice: '同日与可比统计测试', coverage: { total_count: 3, confirmed_count: 2, candidate_count: 1, comparable_count: 1, available_count: 1 } };
vi.mock('../src/components/Chart', () => ({ Chart: ({ title, hasData }: { title: string; hasData: boolean }) => <section aria-label={title}>{title}{!hasData && <p>当前范围没有可绘制数据；缺失不等于零。</p>}</section> }));
/** 功能：提供通知上下文；输入：页面；输出：渲染测试页面。 */
function view(node: React.ReactNode) { return render(<ToastProvider>{node}</ToastProvider>); }

describe('纯份额主线', () => {
  it('首页路由默认份额主线，支持分组编码且损坏地址安全回退', async () => {
    vi.spyOn(api, 'health').mockResolvedValue(health); const read = vi.spyOn(api, 'sharesOverview').mockResolvedValue(overview);
    window.location.hash = '/groups/%E0%A4%A'; render(<App />);
    expect(await screen.findByRole('heading', { name: '份额总览' })).toBeVisible(); await waitFor(() => expect(read).toHaveBeenCalled());
    expect(screen.getByRole('link', { name: '沪深300' })).toHaveAttribute('href', '#/groups/%E6%B2%AA%E6%B7%B1300');
  });
  it('默认共同发布日不同于请求截止时仍按实际日求和', async () => {
    vi.spyOn(api, 'sharesOverview').mockResolvedValue({ ...overview, as_of: '2026-10-29', requested_as_of: '2026-10-29', statistics_date: '2026-10-28' });
    view(<DashboardPage onDetail={vi.fn()} />);
    await screen.findByRole('link', { name: '沪深300' });
    const card = screen.getByText('同日总份额（亿份）', { selector: '.metric > span' }).closest<HTMLElement>('.metric')!;
    expect(within(card).getByText('1.20')).toBeVisible();
    expect(screen.getByText('统计日期：2026-10-28')).toBeVisible();
  });
  it('有界历史日期不使用无限窗口，异常日期返回缺失', () => {
    expect(boundedHistoryStart('2026-10-28')).toBe('2026-05-01'); expect(boundedHistoryStart('2026-99-99')).toBeUndefined(); expect(boundedHistoryStart(undefined)).toBeUndefined();
  });
  it('同日合计不混不同日期，不把未知字段归零', () => {
    expect(sameDayTotal([summary], '2026-10-28', 'total_shares')).toBe(120000000);
    expect(sameDayTotal([summary, { ...summary, trade_date: '2026-10-27' }], '2026-10-28', 'total_shares')).toBeNull();
    expect(sameDayTotal([{ ...summary, delta_shares: null }], '2026-10-28', 'delta_shares')).toBeNull();
    expect(sameDayTotal([], '2026-10-28', 'total_shares')).toBeNull();
  });
  it('仅候选分组不拖累已确认分组首页合计，候选明细仍保留', async () => {
    const candidateOnly: ShareGroupSummary = { ...summary, group: '纯候选组', total_count: 0, candidate_count: 3, available_count: 0, comparable_count: 0, total_shares: null, delta_shares: null, increased: null, decreased: null, trade_date: null, quality: 'missing' };
    vi.spyOn(api, 'sharesOverview').mockResolvedValue({ ...overview, groups: [summary, candidateOnly] });
    view(<DashboardPage onDetail={vi.fn()} />); await screen.findByRole('link', { name: '纯候选组' });
    const metric = (name: string) => within(screen.getByText(name, { selector: '.metric > span' }).closest('.metric')!);
    expect(metric('同日总份额（亿份）').getByText('1.20')).toBeVisible(); expect(metric('可比份额变化（亿份）').getByText('0.02')).toBeVisible();
    expect(metric('增加 / 减少产品').getByText('1 / 0')).toBeVisible(); expect(metric('同日覆盖 / 可比 / 已确认成员').getByText('1 / 1 / 2')).toBeVisible();
    expect(screen.getByRole('row', { name: /纯候选组/ })).toHaveTextContent('分类候选 3');
  });
  it('只有候选分组时合计仍为缺失，不伪造零存量或零变化', async () => {
    vi.spyOn(api, 'sharesOverview').mockResolvedValue({ ...overview, groups: [{ ...summary, group: '纯候选组', total_count: 0, total_shares: 0, delta_shares: 0 }], items: [] });
    view(<DashboardPage onDetail={vi.fn()} />); await screen.findByRole('link', { name: '纯候选组' });
    expect(within(screen.getByText('同日总份额（亿份）', { selector: '.metric > span' }).closest('.metric')!).getByText('—')).toBeVisible();
    expect(within(screen.getByText('可比份额变化（亿份）').closest('.metric')!).getByText('—')).toBeVisible();
  });
  it.each([40, 41])('编码分组路由遵守40字边界：%i字', async length => {
    const name = '组'.repeat(length); window.location.hash = `/groups/${encodeURIComponent(name)}`;
    vi.spyOn(api, 'health').mockResolvedValue(health); vi.spyOn(api, 'sharesOverview').mockResolvedValue(overview);
    const groupRead = vi.spyOn(api, 'shareGroup').mockResolvedValue({ group: { ...summary, group: name }, items: [], mode: 'demo', notice: '' });
    vi.spyOn(api, 'catalogue').mockResolvedValue({ items: [], total: 0, coverage: {} });
    render(<App />);
    expect(await screen.findByRole('heading', { name: length === 40 ? `${name} · 全产品份额` : '份额总览' })).toBeVisible();
    if (length === 40) expect(groupRead).toHaveBeenCalledWith(name, { as_of: undefined, period: 'day' }); else expect(groupRead).not.toHaveBeenCalled();
  });
  it('减少与百分比排行把缺失置于末尾，连续排行不制造零', () => {
    const declining = { ...member, code: '159919', delta_shares: -1000000, delta_pct: -2, increase_streak: 0, decrease_streak: 5 };
    expect(rankShares([missing, member, declining], 'decrease').map(item => item.code)).toEqual(['159919', '510300', '510310']);
    expect(rankShares([missing, declining, member], 'pctIncrease').map(item => item.code)).toEqual(['510300', '159919', '510310']);
    expect(rankShares([member, missing, declining], 'decrease_streak')[0].code).toBe('159919');
  });
  it('首页仅展示份额、可比数与候选，不调用旧盘中仪表盘', async () => {
    vi.spyOn(api, 'sharesOverview').mockResolvedValue(overview); const old = vi.spyOn(api, 'dashboard'); const onDetail = vi.fn();
    view(<DashboardPage onDetail={onDetail} />);
    expect(await screen.findByRole('heading', { name: '份额总览' })).toBeVisible(); await screen.findByText('沪深300ETF');
    expect(screen.getByText('统计日期：2026-10-28')).toBeVisible(); expect(screen.getByText(/同日可用 1\/2 · 可比 1 · 可比覆盖 50.00%/)).toBeVisible();
    expect(screen.getByText('分类候选 1 · 缺失 1')).toBeVisible(); expect(screen.getByText(/原始单位为份/)).toBeVisible();
    expect(screen.queryByText(/行情快照/)).not.toBeInTheDocument(); expect(screen.queryByText(/评分 \/ 覆盖/)).not.toBeInTheDocument(); expect(old).not.toHaveBeenCalled();
    const row = screen.getByRole('row', { name: /缺失产品/ }); expect(within(row).getAllByText('—').length).toBeGreaterThan(0); expect(within(row).getByText('同日份额缺失', { exact: false })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '沪深300ETF' })); expect(onDetail).toHaveBeenCalledWith('510300');
  });
  it('周期日期资产分组映射纯份额请求，更新只提交shares', async () => {
    const read = vi.spyOn(api, 'sharesOverview').mockResolvedValue(overview); const create = vi.spyOn(api, 'createTask').mockResolvedValue({ id: 'share-task', kind: 'shares', status: 'pending', progress: 0, message: '', created_at: '2026-10-29' });
    view(<DashboardPage onDetail={vi.fn()} />); await screen.findByText('沪深300ETF');
    await userEvent.selectOptions(screen.getByLabelText('比较周期'), 'week');
    await waitFor(() => expect(read).toHaveBeenLastCalledWith({ as_of: undefined, period: 'week', asset_class: undefined, group: undefined }));
    await userEvent.selectOptions(screen.getByLabelText('资产类别'), '宽基'); await userEvent.selectOptions(screen.getByLabelText('指数分组'), '沪深300');
    await userEvent.click(screen.getByRole('button', { name: '更新份额' }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ kind: 'shares', group: '沪深300', asset_class: '宽基' }));
    expect(await screen.findByText(/份额任务已受理/)).toBeVisible();
  });
  it('份额接口失败不兜底旧仪表盘，空库与未知覆盖不显正常', async () => {
    vi.spyOn(api, 'sharesOverview').mockRejectedValueOnce(new Error('份额接口不存在（404）')).mockResolvedValue({ ...overview, mode: 'live', groups: [], items: [], coverage: {} });
    view(<DashboardPage onDetail={vi.fn()} />); expect(await screen.findByText('读取失败')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '重试' })); expect(await screen.findByText(/当前范围没有已确认分组/)).toBeVisible();
    expect(screen.queryByText('沪深300ETF')).not.toBeInTheDocument();
  });
  it('覆盖完整不自动变成有效质量，缺计数不为零', () => {
    view(<SharesCoverage group={{ ...summary, available_count: null, comparable_count: null, coverage_pct: null }} />);
    expect(screen.getByText(/同日可用 —\/2 · 可比 — · 可比覆盖 —/)).toBeVisible(); expect(screen.queryByText('有效')).not.toBeInTheDocument();
  });
  it('分组包含缺失成员与分类候选，多线仅请求shares history', async () => {
    vi.spyOn(api, 'shareGroup').mockResolvedValue({ group: summary, items: [member, missing], mode: 'demo', notice: '全产品成员测试' });
    vi.spyOn(api, 'catalogue').mockResolvedValue({ items: [{ code: '510320', name: '候选产品', exchange: 'sh', group: '沪深300', tags: [], enabled: true, asset_class: '宽基', classification_status: 'candidate', classification_evidence: '仅名称规则' }], total: 1, coverage: {} });
    const history = vi.spyOn(api, 'sharesHistory').mockResolvedValue({ items: [], mode: 'demo', frequency: 'day', notice: '' });
    view(<GroupPage group="沪深300" onDetail={vi.fn()} />);
    expect(await screen.findByRole('heading', { name: '沪深300 · 全产品份额' })).toBeVisible(); expect(await screen.findByText('候选产品')).toBeVisible(); expect(screen.getByText('仅名称规则')).toBeVisible();
    expect(screen.getAllByText('缺失产品').length).toBeGreaterThan(0);
    await waitFor(() => expect(history).toHaveBeenCalledWith({ code: '510300', frequency: 'day', start: '2026-05-01', end: '2026-10-28' }));
    await userEvent.selectOptions(screen.getByLabelText('比较周期'), 'month');
    await waitFor(() => expect(history).toHaveBeenCalledWith({ code: '510300', frequency: 'month', start: '2026-05-01', end: '2026-10-28' }));
  });
});
