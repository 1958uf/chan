import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { ETF, SettingsUpdate } from '../api/types';
import { Empty, ResourceStatus, useMutation, useResource } from '../ui';

const emptyETF: ETF = { code: '', name: '', group: '', exchange: 'sh', enabled: true, tags: [] };
/** 功能：新增更新或停用观察标的；输入：无；输出：观察池管理页面。 */
export function WatchlistPage() {
  const resource = useResource(() => api.etfs()); const mutation = useMutation();
  const [draft, setDraft] = useState<ETF>({ ...emptyETF }); const [tags, setTags] = useState('');
  /** 功能：提交观察标的；输入：表单事件；输出：已保存记录与列表刷新。 */
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const record: ETF = { ...draft, name: draft.name.trim(), group: draft.group.trim(), tags: tags.split(/[,，]/).map(item => item.trim()).filter(Boolean) };
    if (await mutation.run(() => api.saveETF(record), '观察标的已保存')) { setDraft({ ...emptyETF }); setTags(''); await resource.reload(); }
  };
  /** 功能：翻转观察状态，不删除历史记录；输入：标的；输出：最新列表。 */
  const toggle = async (etf: ETF) => { if (await mutation.run(() => api.saveETF({ ...etf, enabled: !etf.enabled }), etf.enabled ? '标的已停用，历史记录保留' : '标的已加入观察')) await resource.reload(); };
  return <><div className="page-heading"><div><h1>观察池管理</h1><p>独立系统观察范围 · 停用不删除历史记录</p></div></div><form className="panel form-panel" onSubmit={event => void submit(event)}><h2>{resource.data?.items.some(item => item.code === draft.code) ? '更新观察标的' : '新增观察标的'}</h2><div className="form-grid"><label>六位代码<input value={draft.code} inputMode="numeric" pattern="[0-9]{6}" maxLength={6} onChange={event => setDraft({ ...draft, code: event.target.value })} required /></label><label>ETF 名称<input value={draft.name} maxLength={80} onChange={event => setDraft({ ...draft, name: event.target.value })} required /></label><label>指数分组<input value={draft.group} maxLength={40} onChange={event => setDraft({ ...draft, group: event.target.value })} required /></label><label>交易所<select value={draft.exchange} onChange={event => setDraft({ ...draft, exchange: event.target.value as ETF['exchange'] })}><option value="sh">上海证券交易所</option><option value="sz">深圳证券交易所</option></select></label><label>标签<input value={tags} onChange={event => setTags(event.target.value)} placeholder="逗号分隔" /></label><label>上市日期（可选）<input type="date" value={draft.listed_on || ''} onChange={event => setDraft({ ...draft, listed_on: event.target.value || null })} /></label></div><div className="actions"><label className="checkbox"><input type="checkbox" checked={draft.enabled} onChange={event => setDraft({ ...draft, enabled: event.target.checked })} />启用观察</label><button type="submit" className="primary" disabled={mutation.busy}>保存标的</button><button type="button" onClick={() => { setDraft({ ...emptyETF }); setTags(''); }}>清空表单</button></div></form><ResourceStatus resource={resource} /><section className="panel"><h2>观察列表</h2>{resource.data?.items.length ? <div className="table-wrap"><table><thead><tr><th>ETF</th><th>分组 / 标签</th><th>交易所</th><th>状态</th><th>操作</th></tr></thead><tbody>{resource.data.items.map(item => <tr key={item.code}><td>{item.name}<small className="mono">{item.code}</small></td><td>{item.group}<small>{item.tags.join(' · ')}</small></td><td>{item.exchange.toUpperCase()}</td><td><span className={`badge ${item.enabled ? 'neutral' : 'warn'}`}>{item.enabled ? '观察中' : '已停用'}</span></td><td><div className="actions"><button onClick={() => { setDraft({ ...item }); setTags(item.tags.join(', ')); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>编辑</button><button disabled={mutation.busy} onClick={() => void toggle(item)}>{item.enabled ? '停用' : '启用'}</button></div></td></tr>)}</tbody></table></div> : !resource.loading && <Empty>观察池为空，请新增 ETF。不会自动填入样例标的。</Empty>}</section></>;
}

const fields: { key: Exclude<keyof SettingsUpdate, 'scheduler_enabled'>; label: string; min: number; max: number; step?: number; hint: string }[] = [
  { key: 'quote_interval', label: '行情轮询间隔（秒）', min: 15, max: 3600, hint: '15–3600，调度启用后生效' },
  { key: 'alert_cooldown_seconds', label: '告警冷却（秒）', min: 1, max: 604800, hint: '大于零，避免重复告警；前端限制一周' },
  { key: 'shares_alert_pct', label: '日份额变化告警阈值（%）', min: 0.01, max: 100, step: 0.01, hint: '大于零、至多100，不用于实时申赎判断' },
];
/** 功能：管理非敏感白名单配置；输入：无；输出：配置页面。 */
export function SettingsPage() {
  const resource = useResource(() => api.settings()); const mutation = useMutation();
  const [draft, setDraft] = useState<SettingsUpdate | null>(null);
  useEffect(() => {
    if (!resource.data) return;
    const data = resource.data;
    setDraft({ scheduler_enabled: data.scheduler_enabled, quote_interval: data.quote_interval, alert_cooldown_seconds: data.alert_cooldown_seconds, shares_alert_pct: data.shares_alert_pct });
  }, [resource.data]);
  /** 功能：仅提交可调整阈值与调度；输入：表单事件；输出：配置保存和刷新。 */
  const submit = async (event: FormEvent) => { event.preventDefault(); if (draft && await mutation.run(() => api.saveSettings(draft), '配置已保存')) await resource.reload(); };
  return <><div className="page-heading"><div><h1>运行配置</h1><p>只开放阈值与调度，不设置任意目录、URL 或令牌</p></div></div><ResourceStatus resource={resource} /><div className="notice">当前模式：{resource.data?.mode === 'demo' ? '演示（独立固定 seed 数据库）' : resource.data?.mode === 'live' ? '真实采集' : '未知'}。模式切换由后端启动配置控制；会话令牌仅在内存中使用，变更请求自动携带 X-ETF-Token。</div>{draft && <form className="panel form-panel" onSubmit={event => void submit(event)}><h2>采集与告警参数</h2><p className="muted">源请求超时：{resource.data?.request_timeout ?? '未知'} 秒 · 最大重试：{resource.data?.max_retries ?? '未知'} · 最大回填：{resource.data?.max_backfill_days ?? '未知'} 天（只读，由后端启动配置控制）</p><label className="checkbox"><input type="checkbox" checked={draft.scheduler_enabled} onChange={event => setDraft({ ...draft, scheduler_enabled: event.target.checked })} />启用自动调度（默认关闭）</label><div className="form-grid">{fields.map(field => <label key={field.key}>{field.label}<input aria-label={field.label} type="number" value={draft[field.key] ?? ''} min={field.min} max={field.max} step={field.step || 1} required onChange={event => setDraft({ ...draft, [field.key]: event.target.value === '' ? NaN : Number(event.target.value) })} /><small>{field.hint}</small></label>)}</div><button className="primary" disabled={mutation.busy || !!resource.error}>保存配置</button></form>}</>;
}
