import { useMemo, useState, type FormEvent } from 'react';
import type { EChartsOption } from 'echarts';
import { api } from '../api/client';
import type { HolderRecord, ShareHistoryItem, SharePeriod, SharesHistory } from '../api/types';
import { Chart } from '../components/Chart';
import { Badge, billion, download, Empty, number, ResourceStatus, useMutation, useResource, useToast } from '../ui';
import { HolderTable } from './Detail';

const periods: Record<SharePeriod | 'unknown', string> = { day: '日', week: '周', month: '月', unknown: '未知' };
interface HistoryFilters { start: string; end: string; frequency: SharePeriod; group: string; code: string }
const historyFields = ['date', 'code', 'name', 'group', 'asset_class', 'shares', 'total_shares', 'delta_shares', 'delta_pct', 'comparable_count', 'total_count', 'coverage_pct', 'quality', 'reason', 'source', 'baseline_date', 'trade_date', 'availability_pct', 'available_count', 'candidate_count', 'unclassified_count', 'missing_count', 'new_count', 'exited_count', 'increased', 'decreased', 'unchanged'] as const;

/** 功能：读取原始期末份额并保留缺失；输入：产品或分组历史记录；输出：份额或空值，不进行日期求和。 */
function periodShares(item: ShareHistoryItem): number | null {
  const value = item.shares !== undefined ? item.shares : item.total_shares;
  return value != null && Number.isFinite(value) ? value : null;
}

/** 功能：将后端期末记录绘为多线份额图；输入：当前查询记录；输出：亿份图表配置，不把周月存量累加。 */
export function sharesHistoryChart(items: ShareHistoryItem[]): EChartsOption {
  const dates = [...new Set(items.map(item => item.date))].sort();
  const lines = new Map<string, { name: string; values: Map<string, number | null> }>();
  items.forEach(item => {
    const key = item.code ? `code:${item.code}` : `group:${item.group || '未分类'}`;
    const line = lines.get(key) || { name: item.code ? `${item.code}${item.name ? ` ${item.name}` : ''}` : item.group || '未分类', values: new Map<string, number | null>() };
    const value = periodShares(item);
    // 后端负责周/月期末采样；同日期只保留原始存量，不累加日份额，也不跨缺失连线。
    line.values.set(item.date, value == null ? null : value / 1e8);
    lines.set(key, line);
  });
  return {
    tooltip: { trigger: 'axis' }, legend: { type: 'scroll', top: 0 },
    grid: { left: 70, right: 25, top: 55, bottom: 70 },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value', name: '亿份', splitLine: { lineStyle: { color: '#22304a' } } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 10 }],
    series: [...lines.values()].map(line => ({ type: 'line' as const, name: line.name, connectNulls: false, data: dates.map(date => line.values.get(date) ?? null) })),
  };
}

/** 功能：序列化当前查询的纯份额结果；输入：返回快照、已提交筛选与格式；输出：本地 Blob，含模式及口径，不导出 NAV/评分字段。 */
export function sharesHistoryBlob(data: SharesHistory, filters: HistoryFilters, format: 'csv' | 'json'): Blob {
  const items = data.items.map(item => Object.fromEntries(historyFields.filter(key => key in item).map(key => [key, item[key as keyof ShareHistoryItem]])));
  const metadata = { mode: data.mode, frequency: data.frequency, notice: data.notice, filters };
  if (format === 'json') return new Blob([JSON.stringify({ ...metadata, items }, null, 2)], { type: 'application/json;charset=utf-8' });
  /** 功能：转义 CSV 单元格并阻止文本公式注入；输入：单元格原值；输出：引号包裹的安全文本。 */
  const cell = (value: unknown): string => {
    let text = value == null ? '' : String(value);
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const rows = [
    ['# mode', data.mode], ['# frequency', data.frequency], ['# notice', data.notice], ['# filters', JSON.stringify(filters)],
    [...historyFields], ...items.map(item => historyFields.map(key => item[key])),
  ];
  return new Blob(['﻿', rows.map(row => row.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
}

/** 功能：查询日/周/月纯份额历史并导出当前快照；输入：无；输出：历史份额页，周月按后端期末存量展示。 */
export function HistoryPage() {
  const [filters, setFilters] = useState<HistoryFilters>({ start: '', end: '', frequency: 'day', group: '', code: '' });
  const [draft, setDraft] = useState(filters);
  const groups = useResource(() => api.sharesOverview());
  const resource = useResource(async () => ({ ...(await api.sharesHistory(filters)), filters: { ...filters } }), [filters.start, filters.end, filters.frequency, filters.group, filters.code]);
  const mutation = useMutation(); const notify = useToast();
  const items = resource.data?.items || [];
  const option = useMemo(() => sharesHistoryChart(items), [items]);
  /** 功能：验证查询范围与产品代码；输入：表单事件；输出：提交合法份额筛选。 */
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.start && draft.end && draft.start > draft.end) { notify('开始日期不能晚于结束日期', 'error'); return; }
    const code = draft.code.trim();
    if (code && !/^\d{6}$/.test(code)) { notify('ETF 代码必须是六位数字', 'error'); return; }
    setFilters({ ...draft, code });
  };
  /** 功能：下载已成功返回的当前查询快照；输入：文件格式；输出：本地纯份额文件，失败或加载中不误用旧查询。 */
  const exportData = (format: 'csv' | 'json') => mutation.run(async () => {
    if (!resource.data || resource.loading || resource.error) throw new Error('当前查询尚未成功返回，不能导出');
    download(sharesHistoryBlob(resource.data, resource.data.filters, format), `ETF-份额历史-${resource.data.frequency}.${format}`);
  }, `${format.toUpperCase()} 已导出（仅当前查询返回的纯份额数据）`);
  return <>
    <div className="page-heading"><div><h1>历史份额</h1><p>日 / 周 / 月期末存量与可比变化 · 单位亿份 · 不依赖净值或行情</p></div><div className="actions"><button disabled={mutation.busy || resource.loading || !!resource.error || !resource.data} onClick={() => void exportData('csv')}>导出 CSV</button><button disabled={mutation.busy || resource.loading || !!resource.error || !resource.data} onClick={() => void exportData('json')}>导出 JSON</button></div></div>
    <form className="toolbar" onSubmit={submit}>
      <label>频率<select value={draft.frequency} onChange={event => setDraft({ ...draft, frequency: event.target.value as SharePeriod })}>{(['day', 'week', 'month'] as const).map(value => <option key={value} value={value}>{periods[value]}</option>)}</select></label>
      <label>指数分组<select value={draft.group} onChange={event => setDraft({ ...draft, group: event.target.value })}><option value="">全部分组</option>{[...new Set(groups.data?.groups.map(item => item.group) || [])].map(group => <option key={group} value={group}>{group}</option>)}</select></label>
      <label>ETF 代码<input inputMode="numeric" maxLength={6} placeholder="留空查询分组" value={draft.code} onChange={event => setDraft({ ...draft, code: event.target.value })} /></label>
      <label>开始日期<input type="date" value={draft.start} onChange={event => setDraft({ ...draft, start: event.target.value })} /></label>
      <label>结束日期<input type="date" value={draft.end} onChange={event => setDraft({ ...draft, end: event.target.value })} /></label>
      <button className="primary" type="submit">查询历史</button>
    </form>
    <ResourceStatus resource={resource} /><ResourceStatus resource={groups} />
    {resource.data && <div className={`notice ${resource.data.mode === 'demo' ? 'warning-notice' : ''}`}><strong>API 模式：{resource.data.mode === 'demo' ? '演示（固定样例，非真实市场）' : resource.data.mode === 'live' ? '真实数据' : '未知'} · 返回频率：{periods[resource.data.frequency]}</strong><span>{resource.data.notice || '接口未提供口径说明，请核对日期、可比数与质量。'}</span></div>}
    <div className="notice">周/月取交易周期末份额存量，不按日求和；缺失不等于零。变化率以同一可比集合的基期份额为分母，覆盖率不等于数据质量；新纳入与退出成员不作为申赎变化。CSV/JSON 仅导出已提交查询的返回记录；PNG 为当前图表。</div>
    <Chart title={`历史${periods[resource.data?.frequency || filters.frequency]}份额（亿份）`} option={option} hasData={items.some(item => periodShares(item) != null)} />
    <section className="panel"><h2>份额历史明细</h2>{items.length ? <div className="table-wrap"><table><thead><tr><th>期末日期</th><th>产品 / 分组</th><th>期末份额（亿份）</th><th>变化（亿份）</th><th>变化率（%）</th><th>可比 / 总数</th><th>可比覆盖（%）</th><th>质量</th></tr></thead><tbody>{items.map((item, index) => <tr key={`${item.date}-${item.code || item.group}-${index}`}><td>{item.date}</td><td>{item.code ? <a href={`#/etfs/${encodeURIComponent(item.code)}`}>{item.code}{item.name ? ` ${item.name}` : ''}</a> : item.group ? <a href={`#/groups/${encodeURIComponent(item.group)}`}>{item.group}</a> : '未分类'}{item.code && <small>{item.group || '未分类'}</small>}</td><td>{billion(periodShares(item))}</td><td>{billion(item.delta_shares)}<small>可比基准 {item.baseline_date || '未知'}</small></td><td>{number(item.delta_pct)}</td><td>{number(item.comparable_count, 0)} / {number(item.total_count, 0)}</td><td>{number(item.coverage_pct)}<small>同日可用 {number(item.availability_pct)}%</small></td><td><Badge value={item.quality} />{item.reason && <small>{item.reason}</small>}</td></tr>)}</tbody></table></div> : !resource.loading && !resource.error && <Empty>当前查询范围无份额历史；不使用虚拟记录或流量替代。</Empty>}</section>
    <p className="muted"><a href="#/legacy-history">旧版估算流量（验证辅助）</a> · <a href="#/catalogue">ETF 发现目录</a></p>
  </>;
}

/** 功能：保留旧版历史流量验证辅助；输入：无；输出：旧历史查询页面，不作为纯份额主线。 */
export function LegacyHistoryPage() {
  const [filters, setFilters] = useState({ group: '', start: '', end: '' });
  const [draft, setDraft] = useState(filters);
  const etfs = useResource(() => api.etfs());
  const resource = useResource(() => api.history(filters), [filters.group, filters.start, filters.end]);
  const mutation = useMutation(); const notify = useToast();
  const items = resource.data?.items || [];
  const totals = useMemo(() => {
    const dates = new Map<string, { flow: number; valid: number; missing: number }>();
    items.forEach(item => {
      const entry = dates.get(item.date) || { flow: 0, valid: 0, missing: 0 };
      if (item.estimated_flow == null) entry.missing += 1; else { entry.flow += item.estimated_flow; entry.valid += 1; }
      dates.set(item.date, entry);
    });
    return [...dates].sort(([a], [b]) => a.localeCompare(b));
  }, [items]);
  const option = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' }, grid: { left: 70, right: 25, top: 35, bottom: 70 },
    xAxis: { type: 'category', data: totals.map(([date]) => date) },
    yAxis: { type: 'value', name: '亿元', splitLine: { lineStyle: { color: '#22304a' } } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 10 }],
    series: [{ type: 'bar', name: '可估算标的合计（亿元）', data: totals.map(([, item]) => ({ value: item.valid ? item.flow / 1e8 : null, itemStyle: { color: item.flow >= 0 ? '#f47d81' : '#57c1b1' } })) }],
  }), [totals]);
  /** 功能：提交合法日期查询；输入：表单事件；输出：更新查询范围。 */
  const submit = (event: FormEvent) => { event.preventDefault(); if (draft.start && draft.end && draft.start > draft.end) { notify('开始日期不能晚于结束日期', 'error'); return; } setFilters({ ...draft }); };
  /** 功能：导出已指定日期范围的数据；输入：格式；输出：服务端下载。 */
  const exportData = (format: 'csv' | 'json') => mutation.run(async () => download(await api.exportData(format, { start: filters.start, end: filters.end }), `ETF-历史.${format}`), `${format.toUpperCase()} 已导出（服务端导出不支持分组筛选，包含该日期范围全部标的）`);
  return <><div className="page-heading"><div><h1>历史资金流量</h1><p>基于日份额差值与同日净值估算 · 不含缺证标的</p></div><div className="actions"><button disabled={mutation.busy} onClick={() => void exportData('csv')}>导出 CSV</button><button disabled={mutation.busy} onClick={() => void exportData('json')}>导出 JSON</button></div></div><form className="toolbar" onSubmit={submit}><label>指数分组<select value={draft.group} onChange={event => setDraft({ ...draft, group: event.target.value })}><option value="">全部分组</option>{[...new Set(etfs.data?.items.map(item => item.group) || [])].map(item => <option key={item}>{item}</option>)}</select></label><label>开始日期<input type="date" value={draft.start} onChange={event => setDraft({ ...draft, start: event.target.value })} /></label><label>结束日期<input type="date" value={draft.end} onChange={event => setDraft({ ...draft, end: event.target.value })} /></label><button className="primary" type="submit">查询历史</button></form><ResourceStatus resource={resource} /><ResourceStatus resource={etfs} /><div className="notice">合计仅代表返回范围内可估算记录，部分缺失时不是完整市场流量。CSV/JSON 按日期导出全部标的，PNG 为当前筛选图表。</div><Chart title="历史日估算流量" option={option} hasData={totals.some(([, entry]) => entry.valid > 0)} /><section className="panel"><h2>历史明细</h2>{items.length ? <div className="table-wrap"><table><thead><tr><th>日期</th><th>ETF / 分组</th><th>日份额（亿份）</th><th>变化（亿份）</th><th>估算流量（亿元）</th><th>质量</th></tr></thead><tbody>{items.map((item, index) => <tr key={`${item.date}-${item.code}-${index}`}><td>{item.date}</td><td>{item.code}<small>{item.group || '未知分组'}</small></td><td>{billion(item.shares)}</td><td>{billion(item.delta_shares)}</td><td>{billion(item.estimated_flow)}</td><td><Badge value={item.quality} /></td></tr>)}</tbody></table></div> : !resource.loading && <Empty>当前查询范围无历史记录，不使用虚拟流量替代。</Empty>}</section></>;
}

/** 功能：查询和人工导入报告期持有人；输入：无；输出：持有人页面。 */
export function HoldersPage() {
  const [code, setCode] = useState(''); const [queryCode, setQueryCode] = useState(''); const [report, setReport] = useState('');
  const [json, setJson] = useState(''); const [showImport, setShowImport] = useState(false);
  const resource = useResource(() => api.holders(queryCode), [queryCode]);
  const mutation = useMutation(); const notify = useToast();
  const reports = [...new Set(resource.data?.items.map(item => item.report_date) || [])].sort().reverse();
  const items = resource.data?.items.filter(item => !report || item.report_date === report) || [];
  /** 功能：校验并提交人工报告 JSON；输入：表单事件；输出：导入结果及刷新。 */
  const importRecords = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const value: unknown = JSON.parse(json);
      const records = Array.isArray(value) ? value : value && typeof value === 'object' && 'records' in value ? value.records : null;
      if (!Array.isArray(records) || !records.length || records.length > 1000) throw new Error('请输入 1–1000 条记录数组或 {records:[…]}；字段由后端严格校验');
      if (await mutation.run(() => api.importHolders(records as HolderRecord[]), '持有人报告已导入')) { setJson(''); await resource.reload(); }
    } catch (error) { notify(error instanceof Error ? error.message : 'JSON 无效', 'error'); }
  };
  return <><div className="page-heading"><div><h1>持有人报告</h1><p>报告期 / 公告日 / 来源可追溯 · 不代表实时持仓</p></div><button onClick={() => setShowImport(!showImport)}>{showImport ? '收起人工导入' : '人工补充报告'}</button></div><form className="toolbar" onSubmit={event => { event.preventDefault(); if (code && !/^\d{6}$/.test(code)) { notify('ETF 代码必须是六位数字', 'error'); return; } setQueryCode(code); setReport(''); }}><label>ETF 代码<input inputMode="numeric" value={code} maxLength={6} onChange={event => setCode(event.target.value)} placeholder="留空查询全部" /></label><label>报告期<select value={report} onChange={event => setReport(event.target.value)}><option value="">全部报告期</option>{reports.map(item => <option key={item}>{item}</option>)}</select></label><button className="primary">查询报告</button></form><div className="notice">公告日未知：不能判断历史时点是否已公开。机构分类只是文本归类，不证明交易主体。</div><ResourceStatus resource={resource} />{showImport && <form className="panel form-panel" onSubmit={event => void importRecords(event)}><h2>人工补充 · 严格 JSON 记录</h2><p className="muted">每条必须包含 code、report_date、holder、source、fetched_at（带时区）、quality；可选 published_on、shares（份）、ratio_pct（0–100）、source_url、institution_group。来源须真实可核验。</p><label>报告 JSON<textarea rows={8} value={json} onChange={event => setJson(event.target.value)} placeholder="粘贴记录数组，禁止虚构来源和公告日期" required /></label><button className="primary" disabled={mutation.busy}>提交报告导入</button></form>}<section className="panel"><div className="panel-title"><h2>报告记录</h2><span className="muted">{number(items.length, 0)} 条 · 返回范围有界</span></div><HolderTable items={items} /></section></>;
}
