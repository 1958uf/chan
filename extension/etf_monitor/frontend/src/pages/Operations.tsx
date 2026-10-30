import { useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { TaskKind, TaskRequest } from '../api/types';
import { Badge, Empty, ResourceStatus, time, useMutation, useResource, useToast } from '../ui';

export const taskNames: Record<TaskKind, string> = { shares: '纯份额更新', catalogue: '发现目录同步', refresh: '即时刷新（辅助）', backfill: '历史回填（辅助）', holders: '持有人采集', market: '市场指标', calendar: '交易日历' };
/** 功能：根据契约百分比限制进度条；输入：任务进度；输出：0–100 百分比，不推断完成状态。 */
export function taskProgress(value: number): number { return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0; }
/** 功能：确认告警并展示未确认状态；输入：无；输出：告警页面。 */
export function AlertsPage() {
  const resource = useResource(() => api.alerts(), [], 15000);
  const [onlyPending, setOnlyPending] = useState(true); const mutation = useMutation();
  const items = resource.data?.items.filter(item => !onlyPending || !item.acknowledged) || [];
  /** 功能：确认指定告警后重新读服务端；输入：编号；输出：状态更新。 */
  const acknowledge = async (id: string | number) => { if (await mutation.run(() => api.acknowledge(id), '告警已确认（确认不等于风险解除）')) await resource.reload(); };
  return <><div className="page-heading"><div><h1>告警中心</h1><p>阈值触发与数据质量问题 · 确认不代表问题解决</p></div><label className="checkbox"><input type="checkbox" checked={onlyPending} onChange={event => setOnlyPending(event.target.checked)} />仅未确认</label></div><ResourceStatus resource={resource} />{items.length ? <div className="alert-list">{items.map(item => <article className={`panel alert-card ${item.severity === 'critical' || item.severity === 'error' ? 'critical' : ''}`} key={item.id}><div className="panel-title"><h2>{item.title}</h2><span className="badge warn">{item.severity}</span></div><p>{item.message}</p><div className="alert-footer"><small>{item.code || '系统'} · {item.kind} · {time(item.created_at)}</small><button className={item.acknowledged ? '' : 'primary'} disabled={item.acknowledged || mutation.busy} onClick={() => void acknowledge(item.id)}>{item.acknowledged ? '已确认' : '确认告警'}</button></div></article>)}</div> : !resource.loading && <Empty>当前没有{onlyPending ? '未确认' : ''}告警。无告警不等于数据完整或市场正常，请同时检查健康状态。</Empty>}</>;
}

/** 功能：创建任务、跟踪进度并取消；输入：无；输出：后台任务页面。 */
export function TasksPage() {
  const resource = useResource(() => api.tasks(), [], 3000);
  const [kind, setKind] = useState<TaskKind>('shares'); const [start, setStart] = useState(''); const [end, setEnd] = useState(''); const [codes, setCodes] = useState('');
  const mutation = useMutation(); const notify = useToast();
  /** 功能：校验任务范围并提交；输入：表单事件；输出：新任务及最新列表。 */
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const selectedCodes = codes.split(/[\s,，]+/).filter(Boolean);
    if (selectedCodes.some(code => !/^\d{6}$/.test(code))) { notify('标的代码必须为六位数字，多个代码用逗号分隔', 'error'); return; }
    if (kind === 'backfill' && (!start || !end)) { notify('历史回填必须填写开始和结束日期', 'error'); return; }
    if (start && end && start > end) { notify('开始日期不能晚于结束日期', 'error'); return; }
    const request: TaskRequest = { kind, ...(start ? { start } : {}), ...(end ? { end } : {}), ...(selectedCodes.length ? { codes: [...new Set(selectedCodes)] } : {}) };
    if (await mutation.run(() => api.createTask(request), '任务已受理，不代表采集已成功')) await resource.reload();
  };
  /** 功能：取消任务并等待后端确认终态；输入：任务编号；输出：任务列表刷新。 */
  const cancel = async (id: string) => { if (await mutation.run(() => api.cancelTask(id), '取消请求已受理，最终状态以后端为准')) await resource.reload(); };
  return <><div className="page-heading"><div><h1>采集任务</h1><p>默认纯份额更新 / 目录发现 / 辅助回填 · 每 3 秒读取进度</p></div><button disabled={resource.loading} onClick={() => void resource.reload()}>刷新任务列表</button></div><form className="panel task-form" onSubmit={event => void submit(event)}><label>任务类型<select value={kind} onChange={event => setKind(event.target.value as TaskKind)}>{Object.entries(taskNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>开始日期<input type="date" value={start} onChange={event => setStart(event.target.value)} required={kind === 'backfill'} /></label><label>结束日期<input type="date" value={end} onChange={event => setEnd(event.target.value)} required={kind === 'backfill'} /></label><label>ETF 代码<input value={codes} onChange={event => setCodes(event.target.value)} placeholder="留空为启用标的，多个用逗号" /></label><button className="primary" disabled={mutation.busy}>创建任务</button></form><div className="notice">日份额通常次日可得；盘中刷新不会制造实时份额。失败与部分成功请结合数据源健康查看；禁止将 100% 进度视为成功。</div><ResourceStatus resource={resource} /><section className="panel">{resource.data?.items.length ? <div className="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>进度</th><th>消息</th><th>创建 / 完成时间</th><th>操作</th></tr></thead><tbody>{resource.data.items.map(item => <tr key={item.id}><td>{taskNames[item.kind] || item.kind}<small className="mono">{item.id}</small></td><td><Badge value={item.status} /></td><td><progress max={100} value={taskProgress(item.progress)} aria-label={`${taskNames[item.kind]}任务进度`} /><small>{taskProgress(item.progress)}%</small></td><td>{item.message || '暂无进度消息'}{item.errors?.map((error, index) => <small className="warn-text" key={index}>{error}</small>)}</td><td>{time(item.created_at)}<small>{item.finished_at ? time(item.finished_at) : '未完成'}</small></td><td><button disabled={mutation.busy || !['pending', 'queued', 'running'].includes(item.status)} onClick={() => void cancel(item.id)}>取消任务</button></td></tr>)}</tbody></table></div> : !resource.loading && <Empty>暂无任务，请在上方创建采集任务。</Empty>}</section></>;
}

/** 功能：呈现源级失败、陈旧和调度状态；输入：无；输出：健康页面。 */
export function HealthPage() {
  const resource = useResource(() => api.health(), [], 15000); const data = resource.data;
  const trustworthy = !!data && ['ok', 'healthy'].includes(data.status) && data.sources.length > 0 && data.sources.every(item => ['ok', 'valid'].includes(item.status) && !!item.last_success && !item.error) && data.mode !== 'demo';
  return <><div className="page-heading"><div><h1>数据源健康</h1><p>网络失败 / 缺失 / 陈旧 / 部分采集，不静默忽略</p></div><button disabled={resource.loading} onClick={() => void resource.reload()}>重新检查</button></div><ResourceStatus resource={resource} />{data && <><div className={`notice ${trustworthy ? '' : 'warning-notice'}`}><strong>{trustworthy ? '服务报告可用；仍需核对各记录时间与质量' : '尚不能认定全部正常：演示、空源、陈旧或失败需要核验'}</strong><span>{data.mode === 'demo' ? '演示服务状态' : '总状态'} <Badge value={data.mode === 'demo' ? 'demo' : data.sources.length === 0 ? 'missing' : data.status} /> · 服务返回：{data.status}（服务状态不等于数据质量） · 服务时钟 {time(data.now)} · 调度 {data.scheduler_enabled ? '已启用' : '已关闭'}</span></div><section className="panel"><h2>源级采集记录</h2>{data.sources.length ? <div className="table-wrap"><table><thead><tr><th>数据源</th><th>状态</th><th>最近成功</th><th>最近尝试</th><th>错误 / 说明</th></tr></thead><tbody>{data.sources.map((item, index) => <tr key={`${item.source}-${index}`}><td className="mono">{item.source}</td><td><Badge value={data.mode === 'demo' && ['ok', 'valid'].includes(item.status) ? 'demo' : item.status} /><small>服务返回：{item.status}</small></td><td>{time(item.last_success)}{!item.last_success && <small className="warn-text">尚无成功证据</small>}</td><td>{time(item.last_attempt || item.checked_at)}</td><td className={item.error ? 'warn-text' : ''}>{item.error || item.message || '未提供说明'}</td></tr>)}</tbody></table></div> : <Empty>没有数据源健康记录，不显示绿色正常；请先触发采集。</Empty>}</section></>}</>;
}
