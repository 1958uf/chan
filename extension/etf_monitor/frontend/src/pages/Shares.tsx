import { useMemo, useState } from 'react';
import type { EChartsOption } from 'echarts';
import { api } from '../api/client';
import type { ShareGroupSummary, ShareItem, SharePeriod } from '../api/types';
import { Chart } from '../components/Chart';
import { Badge, billion, Empty, number, ResourceStatus, useMutation, useResource } from '../ui';

export const assetClasses = ['宽基', '行业', '主题', '风格', '债券', '商品', '跨境', '货币', '未分类'];
/** 功能：格式化份额变化百分比；输入：后端百分数；输出：文本，缺失不补零。 */
export function sharePercent(value: number | null | undefined): string { return value == null ? '—' : `${number(value)}%`; }
/** 功能：说明本接口数据模式与统计口径；输入：模式、提示和日期；输出：保守的来源横幅。 */
export function SharesNotice({ mode, notice, date }: { mode?: string | null; notice?: string | null; date?: string | null }) {
  return <div className="notice" role="status"><strong>{mode === 'demo' ? '份额接口 · 演示样例，不代表真实市场' : mode === 'live' ? '份额接口 · 真实数据，质量须逐项核验' : '份额接口 · 模式未知，不认定为真实有效'}</strong>{notice || '接口未提供额外口径说明，请核验来源与数据质量。'}{date !== undefined && <span>统计日期：{date || '未知'}</span>}<span>原始单位为份，界面按亿份展示。存量不是资金；变化百分比以同一可比集合的基期份额为分母，不识别国家队或其他机构交易。</span></div>;
}
/** 功能：展示分类与同日可比覆盖；输入：分组摘要；输出：不把覆盖完整等同质量有效的文本。 */
export function SharesCoverage({ group }: { group: ShareGroupSummary }) {
  return <span className="coverage-text">同日可用 {group.available_count ?? '—'}/{group.total_count ?? '—'} · 可比 {group.comparable_count ?? '—'} · 可比覆盖 {sharePercent(group.coverage_pct)}<small>分类候选 {group.candidate_count ?? '—'} · 缺失 {group.missing_count ?? '—'}</small><small>新纳入 {group.new_count ?? '—'} · 退出 {group.exited_count ?? '—'} · 同日可用率 {sharePercent(group.availability_pct)}</small></span>;
}
/** 功能：保守求同日分组合计；输入：分组、统计日和指标；输出：数字或缺失，绝不混合不同日期。 */
export function sameDayTotal(groups: ShareGroupSummary[], date: string | null | undefined, field: 'total_shares' | 'delta_shares' | 'increased' | 'decreased' | 'available_count' | 'comparable_count' | 'total_count'): number | null {
  if (!date || !groups.length || groups.some(item => item.trade_date !== date || item[field] == null)) return null;
  return groups.reduce((sum, item) => sum + item[field]!, 0);
}
/** 功能：配置统计日与日周月基线；输入：查询状态和回调；输出：查询控件。 */
function PeriodFields({ asOf, period, onDate, onPeriod }: { asOf: string; period: SharePeriod; onDate: (value: string) => void; onPeriod: (value: SharePeriod) => void }) {
  return <><label>统计日期<input type="date" value={asOf} onChange={event => onDate(event.target.value)} /><small>留空使用后端最新统计日</small></label><label>比较周期<select value={period} onChange={event => onPeriod(event.target.value as SharePeriod)}><option value="day">日 · 前交易日</option><option value="week">周 · 上一自然周末</option><option value="month">月 · 上一自然月末</option></select></label></>;
}
/** 功能：显示纯份额全产品明细；输入：产品与辅助详情回调；输出：含缺失、分类与持续变化的表格。 */
export function SharesTable({ items, onDetail }: { items: ShareItem[]; onDetail: (code: string) => void }) {
  if (!items.length) return <Empty>当前范围没有产品份额记录；未采集与缺失不等于零。</Empty>;
  return <div className="table-wrap"><table><thead><tr><th>产品 / 指数分组</th><th>同日份额（亿份）</th><th>可比变化（亿份）</th><th>变化百分比</th><th>5日 / 20日变化（亿份）</th><th>连续增加 / 减少</th><th>分类 / 质量 / 来源</th></tr></thead><tbody>{items.map(item => <tr key={item.code}><td><button className="link" onClick={() => onDetail(item.code)}>{item.name || item.code}</button><small>{item.code} · {item.group || '未分类'}</small><small>{item.asset_class || '资产类别未知'} · 详情含辅助行情</small></td><td>{billion(item.shares)}<small>份额日期 {item.trade_date || '未知'}</small></td><td className={item.delta_shares == null ? '' : item.delta_shares >= 0 ? 'up' : 'down'}>{billion(item.delta_shares)}<small>基准 {item.baseline_date || '未知'}{item.new_member === true ? ' · 新纳入，独立标记' : ''}</small></td><td>{sharePercent(item.delta_pct)}</td><td>{billion(item.delta_5d)} / {billion(item.delta_20d)}</td><td>{item.increase_streak ?? '—'} / {item.decrease_streak ?? '—'}<small>交易日；断档不延续</small></td><td><span className={`badge ${item.classification_status === 'confirmed' ? 'neutral' : 'warn'}`}>{item.classification_status === 'confirmed' ? '已确认' : item.classification_status === 'candidate' ? '分类候选' : '分类未确认'}</span> <Badge value={item.quality} /><small>{item.source || '来源未知'}{item.reason ? ` · ${item.reason}` : ''}</small></td></tr>)}</tbody></table></div>;
}

type Ranking = 'increase' | 'decrease' | 'pctIncrease' | 'pctDecrease' | 'increase_streak' | 'decrease_streak';
/** 功能：按有值的份额指标排序；输入：产品和排名口径；输出：保留缺值于末尾的列表。 */
export function rankShares(items: ShareItem[], ranking: Ranking): ShareItem[] {
  const field = ranking === 'pctIncrease' || ranking === 'pctDecrease' ? 'delta_pct' : ranking === 'increase_streak' || ranking === 'decrease_streak' ? ranking : 'delta_shares';
  const ascending = ranking === 'decrease' || ranking === 'pctDecrease';
  return [...items].sort((a, b) => {
    const left = a[field]; const right = b[field];
    if (left == null) return right == null ? a.code.localeCompare(b.code) : 1;
    if (right == null) return -1;
    return (ascending ? left - right : right - left) || a.code.localeCompare(b.code);
  });
}
/** 功能：展示份额主线首页；输入：辅助详情跳转函数；输出：同日存量、可比变化与分组排行。 */
export function DashboardPage({ onDetail }: { onDetail: (code: string) => void }) {
  const [asOf, setAsOf] = useState(''); const [period, setPeriod] = useState<SharePeriod>('day');
  const [assetClass, setAssetClass] = useState(''); const [group, setGroup] = useState(''); const [ranking, setRanking] = useState<Ranking>('increase');
  const resource = useResource(() => api.sharesOverview({ as_of: asOf || undefined, period, asset_class: assetClass || undefined, group: group || undefined }), [asOf, period, assetClass, group]);
  const mutation = useMutation(); const data = resource.data;
  // 分组入口来自份额目录而非精选观察池；筛选后保留当前分组，清除筛选即可查看全部。
  const groupChoices = [...new Set([...(data?.groups.map(item => item.group) || []), ...(group ? [group] : [])])];
  const groups = data?.groups || [];
  // 新接口区分请求截止日与共同已发布统计日，保留旧样本兼容但不混合不同日期。
  const date = data?.statistics_date !== undefined ? data.statistics_date : data?.coverage.trade_date ?? data?.as_of;
  // 仅候选分组没有已确认成员，不参与首页合计；候选仍保留在分组明细与覆盖说明中。
  const confirmedGroups = groups.filter(item => item.total_count != null && item.total_count > 0);
  const items = useMemo(() => rankShares(data?.items || [], ranking), [data, ranking]);
  const total = sameDayTotal(confirmedGroups, date, 'total_shares'); const delta = sameDayTotal(confirmedGroups, date, 'delta_shares');
  const option = useMemo<EChartsOption>(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 100, right: 30, top: 25, bottom: 45 }, xAxis: { type: 'value', name: '亿份' }, yAxis: { type: 'category', inverse: true, data: groups.map(item => item.group) }, series: [{ type: 'bar', name: '可比份额变化（亿份）', data: groups.map(item => ({ value: item.delta_shares == null ? null : item.delta_shares / 1e8, itemStyle: { color: item.delta_shares != null && item.delta_shares < 0 ? '#57c1b1' : '#f47d81' } })) }] }), [data]);
  /** 功能：受理纯份额更新，不触发行情净值；输入：当前分类筛选；输出：任务受理提示。 */
  const update = () => mutation.run(() => api.createTask({ kind: 'shares', ...(group ? { group } : {}), ...(assetClass ? { asset_class: assetClass } : {}) }), '份额任务已受理，请在采集任务页核验完成状态；不会采集行情或净值');
  return <><div className="page-heading"><div><h1>份额总览</h1><p>全产品目录 · 同统计日存量 · 可比集合变化</p></div><div className="actions"><button disabled={resource.loading} onClick={() => void resource.reload()}>刷新视图</button><button className="primary" disabled={mutation.busy} onClick={() => void update()}>更新份额</button></div></div><div className="toolbar"><PeriodFields asOf={asOf} period={period} onDate={setAsOf} onPeriod={setPeriod} /><label>资产类别<select value={assetClass} onChange={event => { setAssetClass(event.target.value); setGroup(''); }}><option value="">全部类别</option>{assetClasses.map(item => <option key={item}>{item}</option>)}</select></label><label>指数分组<select value={group} onChange={event => setGroup(event.target.value)}><option value="">全部分组</option>{groupChoices.map(item => <option key={item}>{item}</option>)}</select></label></div><ResourceStatus resource={resource} />{data && <><SharesNotice mode={data.mode} notice={data.notice} date={date} /><div className="metrics"><div className="metric"><span>同日总份额（亿份）</span><strong>{billion(total)}</strong><small>仅已确认分组；不同日期绝不相加</small></div><div className="metric"><span>可比份额变化（亿份）</span><strong className={delta == null ? '' : delta >= 0 ? 'up' : 'down'}>{billion(delta)}</strong><small>首尾都有有效记录的成员差值</small></div><div className="metric"><span>增加 / 减少产品</span><strong>{number(sameDayTotal(confirmedGroups, date, 'increased'), 0)} / {number(sameDayTotal(confirmedGroups, date, 'decreased'), 0)}</strong><small>不将缺记录的成员当成无变化</small></div><div className="metric"><span>同日覆盖 / 可比 / 已确认成员</span><strong>{number(sameDayTotal(confirmedGroups, date, 'available_count'), 0)} / {number(sameDayTotal(confirmedGroups, date, 'comparable_count'), 0)} / {number(sameDayTotal(confirmedGroups, date, 'total_count'), 0)}</strong><small>分类候选不混入完整同指数分母</small></div></div><section className="panel"><h2>接口覆盖口径</h2><div className="coverage-grid">{Object.keys(data.coverage || {}).length === 0 && <span>接口未提供覆盖元数据，不认定目录或交易日历完整。</span>}{Object.entries(data.coverage || {}).map(([key, value]) => <span key={key}>{coverageLabel(key)}：{typeof value === 'number' ? number(value, key.endsWith('_pct') ? 2 : 0) + (key.endsWith('_pct') ? '%' : '') : value == null ? '—' : typeof value === 'string' ? value : typeof value === 'boolean' ? value ? '是' : '否' : JSON.stringify(value)}</span>)}</div></section><Chart title="分组可比份额变化" option={option} hasData={groups.some(item => item.delta_shares != null)} description="亿份 · 各分组以同一可比成员的基期份额计算百分比，不使用总存量作可比分母" /><section className="panel"><div className="panel-title"><h2>类别 / 指数分组 · 全产品入口</h2><a href="#/catalogue">发现与核验分类</a></div>{groups.length ? <div className="table-wrap"><table><thead><tr><th>分组 / 类别</th><th>统计日期</th><th>同日总份额（亿份）</th><th>可比变化（亿份） / 百分比</th><th>增加 / 减少 / 不变</th><th>覆盖 / 分类分母</th><th>质量</th></tr></thead><tbody>{groups.map(item => <tr key={item.group}><td><a href={`#/groups/${encodeURIComponent(item.group)}`}>{item.group}</a><small>{item.asset_class || '未知类别'}</small></td><td>{item.trade_date || '未知'}</td><td>{billion(item.total_shares)}</td><td>{billion(item.delta_shares)} / {sharePercent(item.delta_pct)}</td><td>{item.increased ?? '—'} / {item.decreased ?? '—'} / {item.unchanged ?? '—'}</td><td><SharesCoverage group={item} /></td><td><Badge value={item.quality} /></td></tr>)}</tbody></table></div> : <Empty>当前范围没有已确认分组；请同步目录、核验分类并更新份额，不使用演示数据填补。</Empty>}</section><section className="panel"><div className="panel-title"><h2>产品份额排行</h2><label>排行口径<select value={ranking} onChange={event => setRanking(event.target.value as Ranking)}><option value="increase">份额增加优先</option><option value="decrease">份额减少优先</option><option value="pctIncrease">百分比增加优先</option><option value="pctDecrease">百分比减少优先</option><option value="increase_streak">连续增加优先</option><option value="decrease_streak">连续减少优先</option></select></label></div><p className="muted">缺值保留但置于末尾，不计为零；完整产品列表可进入分组查看。精选观察池仍独立保留。</p><SharesTable items={items} onDetail={onDetail} /></section></>}</>;
}
/** 功能：将后端覆盖字段转换为中文；输入：契约字段；输出：标签，未知字段原样保留供核验。 */
function coverageLabel(key: string): string {
  const labels: Record<string, string> = { total_count: '目录产品数', confirmed_count: '已确认产品', candidate_count: '分类候选', unclassified_count: '未分类', available_count: '同日可用', comparable_count: '首尾可比', missing_count: '份额缺失', coverage_pct: '可比覆盖率', availability_pct: '同日可用率', trade_date: '实际统计日', baseline_date: '可比基准日', calendar_available: '交易日历可用', calendar_complete: '交易日历完整', requested_date: '请求截止日', date_selection: '统计日选择方式', market_latest_dates: '各市最新发布日', missing_markets: '缺失市场', new_count: '新纳入成员', exited_count: '退出成员', total: '目录产品数', available: '同日可用', comparable: '首尾可比', missing: '缺失', suspect: '疑似异常', confirmed: '已确认', candidate: '分类候选', unclassified: '未分类' }; return labels[key] || key;
}
/** 功能：生成有界份额历史起点；输入：后端统计日；输出：前一百八十日或缺失，异常日期不抛出页面错误。 */
export function boundedHistoryStart(end: string | undefined): string | undefined {
  if (!end || !/^\d{4}-\d{2}-\d{2}$/.test(end)) return undefined;
  const timestamp = new Date(`${end}T00:00:00Z`).getTime();
  return Number.isFinite(timestamp) ? new Date(timestamp - 180 * 86400000).toISOString().slice(0, 10) : undefined;
}
/** 功能：展示类别内全产品、分类缺口及最多八条可选份额曲线；输入：分组和辅助详情回调；输出：分组研究页。 */
export function GroupPage({ group, onDetail }: { group: string; onDetail: (code: string) => void }) {
  const [asOf, setAsOf] = useState(''); const [period, setPeriod] = useState<SharePeriod>('day'); const [selected, setSelected] = useState<string[] | null>(null);
  const resource = useResource(() => api.shareGroup(group, { as_of: asOf || undefined, period }), [group, asOf, period]);
  const catalogue = useResource(() => api.catalogue({ group, limit: 5000 }), [group]);
  const items = resource.data?.items || [];
  const codes = selected ?? items.filter(item => item.classification_status === 'confirmed').slice(0, 4).map(item => item.code);
  const end = resource.data?.group.trade_date || asOf || undefined;
  const start = boundedHistoryStart(end);
  const history = useResource(async () => Promise.all(codes.map(async code => ({ code, data: await api.sharesHistory({ code, frequency: period, start, end }) }))), [codes.join(','), period, start, end]);
  const option = useMemo<EChartsOption>(() => {
    const rows = history.data || []; const dates = [...new Set(rows.flatMap(row => row.data.items.map(item => item.date)))].sort();
    return { tooltip: { trigger: 'axis' }, legend: { type: 'scroll', top: 0 }, grid: { left: 65, right: 25, top: 55, bottom: 65 }, xAxis: { type: 'category', data: dates }, yAxis: { type: 'value', name: '亿份' }, dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 5 }], series: rows.map(row => ({ type: 'line', name: items.find(item => item.code === row.code)?.name || row.code, connectNulls: false, showSymbol: false, data: dates.map(date => { const item = row.data.items.find(record => record.date === date); const shares = item?.shares !== undefined ? item.shares : item?.total_shares; return shares == null ? null : shares / 1e8; }) })) };
  }, [history.data, resource.data]);
  const gaps = catalogue.data?.items.filter(item => item.classification_status !== 'confirmed') || [];
  return <><div className="page-heading"><div><h1>{group} · 全产品份额</h1><p>已确认成员与分类候选分开 · 不受精选观察池限制</p></div><a href="#/dashboard">返回份额总览</a></div><div className="toolbar"><PeriodFields asOf={asOf} period={period} onDate={setAsOf} onPeriod={setPeriod} /></div><ResourceStatus resource={resource} />{resource.data && <><SharesNotice mode={resource.data.mode} notice={resource.data.notice} date={resource.data.group.trade_date} /><section className="panel"><div className="panel-title"><h2>分组统计</h2><Badge value={resource.data.group.quality} /></div><p>总份额 {billion(resource.data.group.total_shares)} 亿份 · 可比变化 {billion(resource.data.group.delta_shares)} 亿份 / {sharePercent(resource.data.group.delta_pct)}</p><SharesCoverage group={resource.data.group} /><p className="muted">增加 {resource.data.group.increased ?? '—'} · 减少 {resource.data.group.decreased ?? '—'} · 不变 {resource.data.group.unchanged ?? '—'}；缺失与异常不作为不变。</p></section><section className="panel"><h2>全部成员产品（含份额缺失）</h2><SharesTable items={items} onDetail={onDetail} /></section><section className="panel"><h2>分类候选 / 分类缺口</h2><ResourceStatus resource={catalogue} />{gaps.length ? <div className="table-wrap"><table><thead><tr><th>产品</th><th>分类状态</th><th>依据</th><th>核验入口</th></tr></thead><tbody>{gaps.map(item => <tr key={item.code}><td>{item.name}<small>{item.code}</small></td><td>{item.classification_status === 'candidate' ? '分类候选' : '未分类'}</td><td>{item.classification_evidence || '没有可核验分类依据'}</td><td><a href="#/catalogue">人工确认分类</a></td></tr>)}</tbody></table></div> : !catalogue.loading && <p className="muted">返回目录范围内无分类候选；不代表目录发现覆盖完整。请在发现目录中检查未分类产品。</p>}</section><section className="panel"><h2>多线比较选择</h2><p className="muted">默认前四个已确认成员，最多同时比较八条，查询统计日前 180 天；仅请求份额历史，断档保持断线，日周月均为期末存量。</p><div className="share-selections">{items.filter(item => item.classification_status === 'confirmed').map(item => <label key={item.code} className="checkbox"><input type="checkbox" checked={codes.includes(item.code)} disabled={!codes.includes(item.code) && codes.length >= 8} onChange={event => setSelected(event.target.checked ? [...codes, item.code] : codes.filter(code => code !== item.code))} />{item.name} · {item.code}</label>)}</div></section><ResourceStatus resource={history} />{history.data && history.data.length > 0 && <div className="notice"><strong>成员历史来源口径</strong>{history.data.map(row => <span key={row.code}>{row.code} · 模式 {row.data.mode === 'demo' ? '演示' : row.data.mode === 'live' ? '真实' : '未知'} · 周期 {row.data.frequency === 'day' ? '日' : row.data.frequency === 'week' ? '周' : row.data.frequency === 'month' ? '月' : '未知'} · {row.data.notice || '未提供附加说明'}</span>)}</div>}{history.data?.some(row => row.data.mode !== resource.data?.mode) && <div className="notice warning-notice">历史接口与分组接口模式不同或未知，不能合称为真实同源数据。</div>}<Chart title="成员份额多线对比" option={option} hasData={!!history.data?.some(row => row.data.items.some(item => item.shares != null || item.total_shares != null))} description="亿份 · 独立成员期末存量，不按天加总周/月份额" /></>}</>;
}
