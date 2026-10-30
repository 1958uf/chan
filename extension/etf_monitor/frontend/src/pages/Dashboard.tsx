import { useMemo, useState } from 'react';
import type { EChartsOption } from 'echarts';
import { api } from '../api/client';
import type { GroupSummary, MarketRecord } from '../api/types';
import { Badge, billion, Empty, number, ResourceStatus, time, useResource } from '../ui';
import { Chart } from '../components/Chart';

/** 功能：展示可估算分组样本而不合成质量；输入：分组摘要；输出：中性或缺证样本徽标。 */
export function GroupCoverage({ group }: { group: GroupSummary }) {
  const covered = group.coverage; const count = group.count;
  const complete = count != null && count > 0 && covered === count;
  return <span className={`badge ${complete ? 'neutral' : 'warn'}`} title="可估算样本数 / 分组标的数；完整覆盖不等于来源质量有效">{covered == null ? '样本未提供' : `样本 ${covered}/${count ?? '—'}`}</span>;
}
/** 功能：每个市场指标只取最新交易日，日期相同取最新采集；输入：市场记录；输出：不重复的最新记录。 */
export function latestMarketRecords(records: MarketRecord[]): MarketRecord[] {
  const latest = new Map<MarketRecord['metric'], MarketRecord>();
  records.forEach(item => {
    const previous = latest.get(item.metric);
    if (!previous || item.trade_date > previous.trade_date || (item.trade_date === previous.trade_date && item.fetched_at > previous.fetched_at)) latest.set(item.metric, item);
  });
  return (['turnover', 'margin'] as const).flatMap(metric => { const record = latest.get(metric); return record ? [record] : []; });
}
/** 功能：展示全市场观察摘要和指数分组排名；输入：详情跳转函数；输出：仪表盘页面。 */
export function LegacyDashboardPage({ onDetail }: { onDetail: (code: string) => void }) {
  const resource = useResource(() => api.dashboard(), [], 30000);
  const [group, setGroup] = useState('');
  const data = resource.data;
  const latestMarket = useMemo(() => latestMarketRecords(data?.market || []), [data]);
  const groups = useMemo(() => [...(data?.groups || [])].sort((a, b) => (b.flow ?? -Infinity) - (a.flow ?? -Infinity)), [data]);
  const etfs = useMemo(() => (data?.etfs || []).filter(item => !group || item.group === group).sort((a, b) => (b.estimated_flow ?? -Infinity) - (a.estimated_flow ?? -Infinity)), [data, group]);
  const known = data?.etfs.filter(item => item.estimated_flow !== null) || [];
  const flow = known.length ? known.reduce((total, item) => total + (item.estimated_flow ?? 0), 0) : null;
  const option = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis', valueFormatter: value => value == null ? '缺失' : `${number(Number(value))} 亿元` },
    grid: { left: 110, right: 35, top: 20, bottom: 45 },
    xAxis: { type: 'value', name: '亿元', splitLine: { lineStyle: { color: '#22304a' } } },
    yAxis: { type: 'category', inverse: true, data: groups.map(item => item.group) },
    series: [{ type: 'bar', name: '估算流量', data: groups.map(item => ({ value: item.flow == null ? null : item.flow / 1e8, itemStyle: { color: (item.flow ?? 0) >= 0 ? '#f47d81' : '#57c1b1', borderRadius: [0, 4, 4, 0] } })) }],
  }), [groups]);
  return <><div className="page-heading"><div><h1>监控总览</h1><p>指数分组 · 交易所日份额 · 证据评分</p></div><button onClick={() => void resource.reload()} disabled={resource.loading}>刷新视图</button></div><ResourceStatus resource={resource} />{data && <>
    <div className="notice">{data.notice || '流量为份额变化 × 同日净值的估算，不是实时主力资金，不证明机构交易。'}<span>分析时点：{time(data.as_of)}</span></div>
    <div className="metrics"><div className="metric"><span>观察标的</span><strong>{data.etfs.length}</strong><small>当前后端返回范围</small></div><div className="metric"><span>可估算标的</span><strong>{known.length} <i>/ {data.etfs.length}</i></strong><small>缺净值/份额的不参与求和</small></div><div className="metric"><span>日估算流量（亿元）</span><strong className={flow == null ? '' : flow >= 0 ? 'up' : 'down'}>{billion(flow)}</strong><small>不同份额日期不可视作同日总流量</small></div><div className="metric"><span>质量待核验</span><strong>{data.etfs.filter(item => item.quality !== 'valid').length}</strong><small>演示、陈旧、部分与缺失均非正常</small></div></div>
    <div className="two-col"><Chart title="指数分组流量排名" option={option} hasData={groups.some(item => item.flow !== null)} description="亿元 · 按当前可用估算排序，缺值不参与排名" /><section className="panel"><div className="panel-title"><h2>分组明细</h2><button onClick={() => setGroup('')}>全部</button></div>{groups.length ? <div className="group-list">{groups.map((item, index) => <button className={`group-row ${group === item.group ? 'selected' : ''}`} key={item.group} onClick={() => setGroup(item.group)}><span className="rank">{index + 1}</span><span>{item.group}<small>{item.count == null ? '标的数未知' : `${item.count} 个标的`}</small></span><strong className={item.flow == null ? '' : item.flow >= 0 ? 'up' : 'down'}>{billion(item.flow)}</strong><GroupCoverage group={item} /></button>)}</div> : <Empty>分组数据为空，请检查观察池与采集任务。</Empty>}</section></div>
    <section className="panel"><div className="panel-title"><h2>{group || '全部指数'} · ETF 排行</h2><span className="muted">评分是证据强度，不是上涨概率</span></div>{etfs.length ? <div className="table-wrap"><table><thead><tr><th>ETF / 指数分组</th><th>行情快照（元）</th><th>日份额（亿份）</th><th>份额日变化</th><th>日估算（亿元）</th><th>5日 / 20日（亿元）</th><th>评分 / 覆盖</th><th>质量</th></tr></thead><tbody>{etfs.map(item => <tr key={item.code}><td><button className="link" onClick={() => onDetail(item.code)}>{item.name}</button><small>{item.code} · {item.group}</small></td><td>{number(item.quote_time ? item.price : null, 3)}<small>{item.quote_time ? time(item.quote_time) : item.price != null ? `仅日线参考 ${number(item.price, 3)} 元（非实时）` : '行情未知'}</small></td><td>{billion(item.latest_shares)}<small>份额日期 {item.share_date || '未知'}</small></td><td>{item.delta_pct == null ? '—' : `${number(item.delta_pct)}%`}</td><td className={item.estimated_flow == null ? '' : item.estimated_flow >= 0 ? 'up' : 'down'}>{billion(item.estimated_flow)}</td><td>{billion(item.flow_5d)} / {billion(item.flow_20d)}</td><td>{number(item.score, 0)} / {item.coverage == null ? '未知' : `${number(item.coverage, 0)}%`}<small>{item.label}</small></td><td><Badge value={item.quality} /></td></tr>)}</tbody></table></div> : <Empty />}</section>
    <section className="panel"><h2>市场背景 · 各指标最新日度记录</h2><p className="muted">成交额与融资余额分别取返回范围最新交易日；各自日期可能不同，不以前一日值冒充当日。</p>{latestMarket.length ? <div className="market-grid">{latestMarket.map(item => <div key={item.metric}><span>{item.metric === 'turnover' ? '成交额' : '融资余额'}</span><strong>{billion(item.value)} 亿元</strong><small>{item.trade_date} · {item.source}</small><Badge value={item.quality} /></div>)}</div> : <Empty>市场背景缺失，不据此判断市场健康。</Empty>}</section>
  </>}</>;
}

/** 功能：搜索筛选观察 ETF 并进入详情；输入：详情跳转函数；输出：搜索页。 */
export function ETFPage({ onDetail }: { onDetail: (code: string) => void }) {
  const resource = useResource(() => api.etfs());
  const [search, setSearch] = useState(''); const [group, setGroup] = useState(''); const [enabled, setEnabled] = useState('');
  const groups = [...new Set(resource.data?.items.map(item => item.group) || [])];
  const items = resource.data?.items.filter(item => (!search || `${item.code} ${item.name} ${item.tags.join(' ')}`.toLowerCase().includes(search.toLowerCase())) && (!group || item.group === group) && (!enabled || String(item.enabled) === enabled)) || [];
  return <><div className="page-heading"><div><h1>ETF 检索</h1><p>按代码、名称、标签与指数分组筛选</p></div></div><ResourceStatus resource={resource} /><div className="toolbar"><label>搜索 ETF<input value={search} onChange={event => setSearch(event.target.value)} placeholder="六位代码 / 名称 / 标签" /></label><label>指数分组<select value={group} onChange={event => setGroup(event.target.value)}><option value="">全部分组</option>{groups.map(value => <option key={value}>{value}</option>)}</select></label><label>观察状态<select value={enabled} onChange={event => setEnabled(event.target.value)}><option value="">全部</option><option value="true">观察中</option><option value="false">已停用</option></select></label></div><section className="panel">{items.length ? <div className="etf-grid">{items.map(item => <button className="etf-card" key={item.code} onClick={() => onDetail(item.code)}><div><strong>{item.name}</strong><span className="mono">{item.code} · {item.exchange.toUpperCase()}</span></div><span>{item.group}</span><small>{item.tags.join(' · ') || '无标签'}</small><span className={`badge ${item.enabled ? 'neutral' : 'warn'}`}>{item.enabled ? '观察中' : '已停用'}</span><span className="link">查看行情与份额 →</span></button>)}</div> : !resource.loading && <Empty>{resource.data?.items.length ? '没有符合筛选的 ETF，请调整搜索条件。' : '观察池为空，请到观察池页面新增标的。'}</Empty>}</section></>;
}
