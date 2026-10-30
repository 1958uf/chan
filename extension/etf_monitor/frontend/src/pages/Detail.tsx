import { useEffect, useMemo, useRef, useState } from 'react';
import type { EChartsOption } from 'echarts';
import { api } from '../api/client';
import type { HolderRecord, Indicator, Task } from '../api/types';
import { Chart } from '../components/Chart';
import { Badge, billion, download, Empty, number, ResourceStatus, time, useMutation, useResource, useToast } from '../ui';

/** 功能：展示报告期持有人与公告日期；输入：持有人记录；输出：表格或空状态。 */
export function HolderTable({ items }: { items: HolderRecord[] }) {
  if (!items.length) return <Empty>暂无持有人报告。报告期数据不是实时持仓，公告日期未知的记录不能用于历史已知判断。</Empty>;
  return <div className="table-wrap"><table><thead><tr><th>标的 / 持有人</th><th>报告期</th><th>公告日</th><th>持有份额（亿份）</th><th>比例</th><th>来源 / 质量</th></tr></thead><tbody>{items.map((item, index) => <tr key={`${item.code}-${item.holder}-${item.report_date}-${index}`}><td>{item.holder}<small>{item.code} · {item.institution_group || '机构分类未知'}</small></td><td>{item.report_date}</td><td>{item.published_on || '未知 · 不可用于时点判断'}</td><td>{billion(item.shares)}</td><td>{item.ratio_pct == null ? '—' : `${number(item.ratio_pct)}%`}</td><td>{/^https?:\/\//i.test(item.source_url) ? <a href={item.source_url} target="_blank" rel="noopener noreferrer">{item.source}</a> : item.source}<small>采集：{time(item.fetched_at)}</small><Badge value={item.quality} /></td></tr>)}</tbody></table></div>;
}

/** 功能：显示独立盘中估算线索，不计算或修改日评分；输入：可选盘中指标；输出：估算卡片或明确空状态。 */
export function IntradayIndicators({ items }: { items?: Indicator[] }) {
  return <section className="panel"><div className="panel-title"><h2>盘中辅助线索 · 估算</h2><span className="badge warn">独立展示 · 不纳入日评分</span></div><p className="warn-text">价格位置与量价线性交易进度只提供辅助线索；估算不是实测申赎，不识别机构交易，不是上涨概率。</p><p className="muted">盘中原始值按指标解释读取：价格位置为历史区间百分比，量价线索为估算成交额比值；不使用日份额填补盘中缺证。</p>{items?.length ? <div className="indicator-grid">{items.map((item, index) => <div key={`${item.name}-${index}`}><strong>{item.name}</strong><span>{item.value == null ? '未知' : typeof item.value === 'number' ? number(item.value) : item.value}</span><Badge value={item.state} />{item.quality && <> <Badge value={item.quality} /></>}{item.direction_pct != null && <p>同期价格变化：{number(item.direction_pct)}%</p>}<p>{item.explanation}</p></div>)}</div> : <Empty>暂无可用盘中辅助指标。接口未提供、行情陈旧或历史证据不足均不显示正常，不用日指标替代。</Empty>}</section>;
}

/** 功能：取后端健康时钟对应的中国交易日期，不使用浏览器当前日；输入：健康 now；输出：年月日或异常。 */
export function serviceTradeDate(now: string): string {
  const parsed = new Date(now);
  if (!now || Number.isNaN(parsed.getTime())) throw new Error('后端健康时钟无效，不能确定分钟采集日期');
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(parsed);
  const value = (kind: string) => parts.find(part => part.type === kind)?.value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}
/** 功能：跟踪刚创建的分钟任务，失败可见，终态重读详情但不制造图形；输入：任务和刷新函数；输出：任务进度面板。 */
export function MinuteTaskStatus({ task, onFinished }: { task: Task; onFinished: () => Promise<void> }) {
  const resource = useResource(() => api.tasks(), [task.id], 3000);
  const latest = resource.data?.items.find(item => item.id === task.id);
  const notify = useToast();
  const terminal = useRef<string | null>(null);
  useEffect(() => {
    if (!latest || !['completed', 'partial', 'failed', 'empty', 'cancelled'].includes(latest.status) || terminal.current === latest.status) return;
    terminal.current = latest.status;
    if (latest.status === 'completed') notify('分钟采集任务已完成，正在重新读取真实图表记录');
    else notify(`分钟采集${latest.status === 'failed' ? '失败' : latest.status === 'partial' ? '部分成功' : latest.status === 'empty' ? '无数据' : '已取消'}：${latest.message || '请检查任务与数据源健康'}`, 'error');
    void onFinished();
  }, [latest, notify, onFinished]);
  return <section className="panel" aria-label="分钟采集任务"><div className="panel-title"><h2>分钟采集任务</h2><a href="#/tasks">查看任务中心</a></div><ResourceStatus resource={resource} />{latest ? <><div className="actions"><Badge value={latest.status} /><span>{latest.interval || task.interval} · {latest.start || task.start} · {latest.id}</span></div><p>{latest.message || '暂无进度说明'}</p>{latest.errors?.map((error, index) => <p className="warn-text" key={index}>{error}</p>)}<p className="muted">任务进入终态后会触发真实详情刷新；部分、失败或空结果不会补画日线作为分钟线。</p></> : !resource.loading && <Empty>当前有界任务列表未返回该任务，状态未知；请到任务中心核验，不能认定采集成功。</Empty>}</section>;
}

/** 功能：展示单只 ETF 行情、日份额、双轴图和报告；输入：代码及返回函数；输出：详情页。 */
export function DetailPage({ code, onBack }: { code: string; onBack: () => void }) {
  const resource = useResource(() => api.detail(code), [code], 30000);
  const [interval, setInterval] = useState<'day' | '1m' | '5m'>('day');
  const mutation = useMutation();
  const [minuteTask, setMinuteTask] = useState<Task | null>(null);
  const data = resource.data;
  const bars = useMemo(() => (data?.bars || []).filter(item => item.interval === interval).sort((a, b) => a.time.localeCompare(b.time)), [data, interval]);
  const shares = useMemo(() => [...(data?.shares || [])].sort((a, b) => a.trade_date.localeCompare(b.trade_date)), [data]);
  const priceOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis' }, grid: { left: 70, right: 30, top: 35, bottom: 80 },
    xAxis: { type: 'category', data: bars.map(item => interval === 'day' ? item.time.slice(0, 10) : time(item.time)) },
    yAxis: { type: 'value', scale: true, name: '元', splitLine: { lineStyle: { color: '#22304a' } } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 15 }],
    series: [{ type: 'candlestick', name: '不复权 OHLC', data: bars.map(item => [item.open, item.close, item.low, item.high]), itemStyle: { color: '#f47d81', color0: '#57c1b1', borderColor: '#f47d81', borderColor0: '#57c1b1' } }],
  }), [bars, interval]);
  const dualOption = useMemo<EChartsOption>(() => {
    const navs = new Map((data?.navs || []).map(item => [item.trade_date, item.nav]));
    return {
      tooltip: { trigger: 'axis' }, legend: { data: ['日份额（亿份）', '同日净值（元）'], textStyle: { color: '#a7b7d0' } },
      grid: { left: 70, right: 65, top: 50, bottom: 70 },
      xAxis: { type: 'category', data: shares.map(item => item.trade_date) },
      yAxis: [{ type: 'value', name: '亿份', scale: true, splitLine: { lineStyle: { color: '#22304a' } } }, { type: 'value', name: '元', scale: true, splitLine: { show: false } }],
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 10 }],
      series: [{ type: 'line', name: '日份额（亿份）', symbol: 'none', data: shares.map(item => item.shares / 1e8), lineStyle: { color: '#6e9eff' }, connectNulls: false }, { type: 'line', name: '同日净值（元）', yAxisIndex: 1, symbol: 'none', data: shares.map(item => navs.get(item.trade_date) ?? null), lineStyle: { color: '#f3c570' }, connectNulls: false }],
    };
  }, [shares, data]);
  /** 功能：按后端当天与当前分钟周期创建刷新任务；输入：无；输出：受理状态，真实结果由任务跟踪读取。 */
  const collectMinutes = () => mutation.run(async () => {
    if (interval === 'day') throw new Error('请先选择1分钟或5分钟周期');
    const health = await api.health();
    const date = serviceTradeDate(health.now);
    const request = { kind: 'refresh' as const, codes: [code], start: date, end: date, interval };
    const task = await api.createTask(request);
    setMinuteTask({ ...task, interval: task.interval || interval, start: task.start || date, end: task.end || date });
  }, '分钟采集任务已受理，不代表已取得分钟数据，请查看下方任务状态');
  /** 功能：下载服务端详情导出；输入：文件格式；输出：真实下载或错误提示。 */
  const exportData = (format: 'csv' | 'json') => mutation.run(async () => download(await api.exportData(format, { code }), `ETF-${code}.${format}`), `${format.toUpperCase()} 导出成功`);
  return <><div className="page-heading"><div><button className="link" onClick={onBack}>← 返回 ETF 检索</button><h1>{data?.etf.name || code} <span className="mono">{code}</span></h1><p>{data?.etf.group || '正在读取标的信息'}</p></div><div className="actions"><button disabled={mutation.busy} onClick={() => void exportData('csv')}>CSV</button><button disabled={mutation.busy} onClick={() => void exportData('json')}>JSON</button><button className="primary" disabled={mutation.busy} onClick={() => void mutation.run(() => api.createTask({ kind: 'refresh', codes: [code] }), '刷新任务已创建，请到任务页跟踪')}>刷新标的</button></div></div><ResourceStatus resource={resource} />{data && <>
    <div className="notice">实时/快照行情与交易所日份额分开显示；日份额不是盘中实时申赎，估算流量不是交易所确认现金流。</div>
    <div className="two-col"><section className="panel snapshot"><h2>行情快照 <span className="badge neutral">非份额</span></h2><strong className="large-number">{number(data.analysis.quote_time ? data.analysis.price : null, 3)} <small>元</small></strong><p>行情源时间：{time(data.analysis.quote_time)}</p><p>行情源时差：{data.analysis.quote_age_seconds == null ? '未知（未提供年龄）' : data.analysis.quote_age_seconds < 0 ? '异常（源时间晚于分析时点）' : `${number(data.analysis.quote_age_seconds, 0)} 秒`}<small> · 相对服务分析时点，不代表浏览器当前时刻的新鲜度</small></p>{!data.analysis.quote_time && data.analysis.price != null && <p className="warn-text">仅有历史日线参考价 {number(data.analysis.price, 3)} 元 · {time(data.analysis.price_time)}，不是行情快照。</p>}<p>溢价率：{data.analysis.premium_pct == null ? '—' : `${number(data.analysis.premium_pct)}%`}</p>{data.quotes.length ? <div className="muted">来源：{data.quotes.at(-1)?.source} · 采集：{time(data.quotes.at(-1)?.fetched_at)} <Badge value={data.quotes.at(-1)?.quality} /></div> : <p className="warn-text">无行情记录，不能判断当前价格。</p>}</section><section className="panel snapshot"><h2>交易所日份额 <span className="badge neutral">日度</span></h2><strong className="large-number">{billion(data.analysis.latest_shares)} <small>亿份</small></strong><p>份额日期：{data.analysis.share_date || '未知'} · 变化：{data.analysis.delta_pct == null ? '—' : `${number(data.analysis.delta_pct)}%`}</p><p>估算日流量：{billion(data.analysis.estimated_flow)} 亿元</p><Badge value={data.analysis.quality} /><p className="muted">仅同日净值与连续有效份额可估算；缺证不归零。</p></section></div>
    <div className="panel-title interval-title"><h2>行情走势</h2><div className="segmented">{interval !== 'day' && <button className="primary" disabled={mutation.busy} onClick={() => void collectMinutes()}>采集分钟</button>}{(['day', '1m', '5m'] as const).map(value => <button key={value} aria-pressed={interval === value} className={interval === value ? 'selected' : ''} onClick={() => setInterval(value)}>{value === 'day' ? '日线' : value === '1m' ? '1分钟' : '5分钟'}</button>)}</div></div>
    {minuteTask && <MinuteTaskStatus key={minuteTask.id} task={minuteTask} onFinished={resource.reload} />}
    <Chart title={interval === 'day' ? '日线 · 不复权' : `${interval === '1m' ? '1' : '5'}分钟行情`} option={priceOption} hasData={bars.length > 0} description={`共 ${bars.length} 条后端记录；分钟缺失不使用日线代替。`} />
    <Chart title="日份额 / 同日净值双轴" option={dualOption} hasData={shares.length > 0} description="左轴亿份、右轴元，缺少同日净值时右轴断线，不进行前向填充。" />
    <section className="panel"><div className="panel-title"><h2>证据指标</h2><span>评分 {number(data.analysis.score, 0)} · 覆盖 {data.analysis.coverage == null ? '未知' : `${number(data.analysis.coverage, 0)}%`} · {data.analysis.label}</span></div><p className="warn-text">评分表示规则证据强度，不是上涨概率，也不是机构身份识别。</p><p className="muted">日评分由后端固定权重计算，未知证据回中性，不对已知项重归一；盘中线索单独展示，不进入日评分。</p>{data.analysis.indicators.length ? <div className="indicator-grid">{data.analysis.indicators.map((item, index) => <div key={`${item.name}-${index}`}><strong>{item.name}</strong><span>{item.value == null ? '未知' : String(item.value)}</span><Badge value={item.state} /><p>{item.explanation}</p></div>)}</div> : <Empty>指标证据不足，不显示绿色正常结论。</Empty>}</section>
    <IntradayIndicators items={data.analysis.intraday_indicators} />
    <section className="panel"><h2>持有人 · 报告期信息</h2><p className="muted">历史可知性以公告日为界；不将历史报告描述为实时持仓。</p><HolderTable items={data.holders} /></section>
    <section className="panel"><h2>日份额原始记录</h2>{shares.length ? <div className="table-wrap"><table><thead><tr><th>交易日期</th><th>份额（份）</th><th>来源</th><th>采集时间</th><th>质量</th></tr></thead><tbody>{shares.slice(-60).reverse().map(item => <tr key={`${item.trade_date}-${item.source}`}><td>{item.trade_date}</td><td>{number(item.shares, 0)}</td><td>{item.source}</td><td>{time(item.fetched_at)}</td><td><Badge value={item.quality} /></td></tr>)}</tbody></table></div> : <Empty />}</section>
  </>}</>;
}
