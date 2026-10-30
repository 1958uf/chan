import { useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { ClassificationRequest, ClassificationStatus, ETF, Task, TaskKind } from '../api/types';
import { Badge, Empty, number, ResourceStatus, time, useMutation, useResource, useToast } from '../ui';

// 资产类为人工确认白名单；“未分类”只用于检索，不作为已确认资产类。
const assetClasses = ['宽基', '行业', '主题', '风格', '债券', '商品', '跨境', '货币'] as const;
const classificationNames: Record<string, string> = { confirmed: '已确认', candidate: '候选待核验', unclassified: '未分类' };
interface CatalogueFilters { asset_class: string; group: string; classification_status: Exclude<ClassificationStatus, 'unknown'> | ''; q: string }

/** 功能：展示发现目录、来源证据与人工分类，并提交独立采集任务；输入：无；输出：分页目录页，不把任务受理当采集完成。 */
export function CataloguePage() {
  const [filters, setFilters] = useState<CatalogueFilters>({ asset_class: '', group: '', classification_status: '', q: '' });
  const [draft, setDraft] = useState(filters);
  const [offset, setOffset] = useState(0);
  const catalogue = useResource(() => api.catalogue({ ...filters, classification_status: filters.classification_status || undefined, limit: 100, offset }), [filters.asset_class, filters.group, filters.classification_status, filters.q, offset]);
  const groups = useResource(() => api.sharesOverview());
  const [selected, setSelected] = useState<ETF | null>(null);
  const [classification, setClassification] = useState({ group: '', asset_class: '', tracking_index: '' });
  const [evidenceChecked, setEvidenceChecked] = useState(false);
  const [submittedTasks, setSubmittedTasks] = useState<Task[]>([]);
  const taskResource = useResource(() => submittedTasks.length ? api.tasks() : Promise.resolve({ items: [] as Task[] }), [submittedTasks.map(task => task.id).join(',')], 3000);
  const mutation = useMutation(); const notify = useToast();
  const items = catalogue.data?.items || [];
  const total = catalogue.data?.total;
  const tasks = submittedTasks.map(task => taskResource.data?.items.find(item => item.id === task.id) || task);

  /** 功能：提交目录筛选并重置分页；输入：表单事件；输出：资产类、组、分类状态与关键词查询。 */
  const submitFilters = (event: FormEvent) => { event.preventDefault(); setFilters({ ...draft, group: draft.group.trim(), q: draft.q.trim() }); setOffset(0); };
  /** 功能：准备人工确认表单；输入：目录记录；输出：待编辑分类及未勾选的证据确认。 */
  const editClassification = (item: ETF) => {
    setSelected(item);
    setClassification({ group: item.group === '未分类' ? '' : item.group, asset_class: assetClasses.includes(item.asset_class as typeof assetClasses[number]) ? item.asset_class || '' : '', tracking_index: item.tracking_index || '' });
    setEvidenceChecked(false);
  };
  /** 功能：严格白名单提交人工分类；输入：表单事件；输出：confirmed 分类保存并刷新目录，不更改观察池。 */
  const confirmClassification = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !/^\d{6}$/.test(selected.code)) { notify('ETF 代码必须是六位数字', 'error'); return; }
    const group = classification.group.trim(); const trackingIndex = classification.tracking_index.trim();
    if (!group || group === '未分类' || group.length > 40 || !assetClasses.includes(classification.asset_class as typeof assetClasses[number]) || trackingIndex.length > 100) { notify('请填写有效分组（1–40 字）、白名单资产类及跟踪指数（最多 100 字）', 'error'); return; }
    if (!evidenceChecked) { notify('请先核对真实来源及跟踪指数，确认候选证据不是最终分类', 'error'); return; }
    // 不展开 ETF 对象：enabled、来源、名称、manual_classification 等字段不得越界提交。
    const request: ClassificationRequest = { code: selected.code, group, asset_class: classification.asset_class, tracking_index: trackingIndex || undefined, classification_status: 'confirmed' };
    if (await mutation.run(() => api.classifyETF(request), '人工分类已保存；不改变独立观察池')) { setSelected(null); await catalogue.reload(); await groups.reload(); }
  };
  /** 功能：提交目录同步或纯份额更新并跟踪真实状态；输入：catalogue/shares 任务类型；输出：受理记录或显式错误，不假报采集完成。 */
  const createTask = async (kind: Extract<TaskKind, 'catalogue' | 'shares'>) => {
    await mutation.run(async () => {
      const task = await api.createTask({ kind, ...(kind === 'shares' && filters.group ? { group: filters.group } : {}), ...(kind === 'shares' && filters.asset_class && filters.asset_class !== '未分类' ? { asset_class: filters.asset_class } : {}) });
      setSubmittedTasks(previous => [task, ...previous.filter(item => item.id !== task.id)]);
    }, '任务已受理，不代表采集成功；可能失败或部分成功，请核对后端状态');
  };

  return <>
    <div className="page-heading"><div><h1>ETF 发现目录</h1><p>交易所目录 / 分类证据 / 人工确认 · 每页最多 100 条</p></div><div className="actions"><button disabled={mutation.busy} onClick={() => void createTask('catalogue')}>同步发现目录</button><button className="primary" disabled={mutation.busy} onClick={() => void createTask('shares')}>更新日份额</button></div></div>
    <div className="notice">发现目录与<a href="#/watchlist">精选观察池</a>独立：同步不会把全部产品自动加入观察池。候选名称规则不证明同指数成员；人工确认前请核对基金文件与跟踪指数。份额更新仅针对目录中已确认且启用的产品，不采集实时净值、评分或行情。</div>
    <form className="toolbar" onSubmit={submitFilters}>
      <label>资产类<select value={draft.asset_class} onChange={event => setDraft({ ...draft, asset_class: event.target.value })}><option value="">全部资产类</option>{[...assetClasses, '未分类'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>分组<input list="catalogue-groups" maxLength={100} value={draft.group} placeholder="全部分组，可输入" onChange={event => setDraft({ ...draft, group: event.target.value })} /><datalist id="catalogue-groups">{[...new Set(groups.data?.groups.map(item => item.group) || [])].map(group => <option key={group} value={group} />)}</datalist></label>
      <label>分类状态<select value={draft.classification_status} onChange={event => setDraft({ ...draft, classification_status: event.target.value as CatalogueFilters['classification_status'] })}><option value="">全部分类状态</option>{Object.entries(classificationNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
      <label>检索<input maxLength={100} value={draft.q} placeholder="代码 / 名称 / 指数" onChange={event => setDraft({ ...draft, q: event.target.value })} /></label>
      <button className="primary" type="submit">查询目录</button>
    </form>
    <p className="muted">目录同步发现全目录；份额更新采用已提交的资产类 / 分组范围{filters.asset_class || filters.group ? `：${filters.asset_class || '全部资产类'} / ${filters.group || '全部分组'}` : '（全部已确认且启用产品）'}。关键词、分类状态和分页不作为采集范围。</p>
    <ResourceStatus resource={catalogue} /><ResourceStatus resource={groups} />
    {catalogue.data && <div className={`notice ${catalogue.data.mode === 'demo' ? 'warning-notice' : ''}`}><strong>API 模式：{catalogue.data.mode === 'demo' ? '演示（固定样例，非真实市场）' : catalogue.data.mode === 'live' ? '真实数据' : '未知'}</strong><span>{catalogue.data.notice || '目录不代表分类或份额覆盖完整，请逐项核对证据。'}</span>{catalogue.data.coverage && <details><summary>目录覆盖 / 来源（API 返回）</summary><pre>{JSON.stringify(catalogue.data.coverage, null, 2)}</pre></details>}</div>}
    {selected && <form className="panel form-panel" onSubmit={event => void confirmClassification(event)}><div className="panel-title"><h2>人工确认分类 · {selected.code} {selected.name}</h2><button type="button" onClick={() => setSelected(null)}>取消确认</button></div><p className="muted">证据：{selected.classification_evidence || '未提供；请自行核对真实基金文件'}<br />目录来源：{selected.catalogue_source || '未知'} · 当前状态：{classificationNames[selected.classification_status || 'unclassified'] || '未知'}</p><label>确认代码<input readOnly value={selected.code} /></label><label>确认分组<input value={classification.group} maxLength={40} onChange={event => setClassification({ ...classification, group: event.target.value })} /></label><label>确认资产类<select value={classification.asset_class} onChange={event => setClassification({ ...classification, asset_class: event.target.value })}><option value="">请选择已核验资产类</option>{assetClasses.map(value => <option key={value}>{value}</option>)}</select></label><label>跟踪指数<input maxLength={100} value={classification.tracking_index} onChange={event => setClassification({ ...classification, tracking_index: event.target.value })} placeholder="基金文件中的准确指数，可留空" /></label><label className="checkbox"><input type="checkbox" checked={evidenceChecked} onChange={event => setEvidenceChecked(event.target.checked)} />已核验来源、资产类与分组；候选规则不作为确认依据</label><button className="primary" disabled={mutation.busy}>保存人工确认</button></form>}
    <section className="panel"><div className="panel-title"><h2>目录产品</h2><span className="muted">总计 {number(total, 0)} 条{items.length ? ` · 当前 ${offset + 1}–${offset + items.length}` : ''}</span></div>{items.length ? <div className="table-wrap"><table><thead><tr><th>ETF</th><th>资产类 / 分组</th><th>分类状态</th><th>跟踪指数 / 证据</th><th>目录来源 / 发现时间</th><th>启用 / 操作</th></tr></thead><tbody>{items.map(item => <tr key={item.code}><td><a href={`#/etfs/${encodeURIComponent(item.code)}`}>{item.code} {item.name}</a><small>{item.exchange === 'sh' ? '上交所' : '深交所'}{item.manager ? ` · ${item.manager}` : ''}</small></td><td>{item.asset_class || '未分类'}<small>{item.group || '未分类'}</small></td><td><span className={`badge ${item.classification_status === 'confirmed' ? 'neutral' : 'warn'}`}>{classificationNames[item.classification_status || 'unclassified'] || '未知'}</span>{item.manual_classification && <small>人工确认</small>}</td><td>{item.tracking_index || '跟踪指数未核验'}<small>{item.classification_evidence || '未提供分类证据'}</small>{item.classification_status !== 'confirmed' && <small className="warn-text">候选 / 未分类不视为已确认同指数成员</small>}</td><td>{item.catalogue_source || '来源未知'}<small>{time(item.discovered_at)}</small></td><td>{item.enabled ? '已启用' : '已停用'}<small><button disabled={mutation.busy} onClick={() => editClassification(item)}>{item.classification_status === 'confirmed' ? '修订分类' : '人工确认'}</button></small></td></tr>)}</tbody></table></div> : !catalogue.loading && !catalogue.error && <Empty>当前筛选无目录产品。可同步发现目录并检查任务结果，不用观察池冒充完整目录。</Empty>}<div className="actions"><button disabled={catalogue.loading || !!catalogue.error || offset === 0} onClick={() => setOffset(previous => Math.max(0, previous - 100))}>上一页</button><span>第 {Math.floor(offset / 100) + 1} 页 · 每页 100 条</span><button disabled={catalogue.loading || !!catalogue.error || total == null || offset + 100 >= total} onClick={() => setOffset(previous => previous + 100)}>下一页</button></div></section>
    {submittedTasks.length > 0 && <section className="panel"><div className="panel-title"><h2>本页提交任务</h2><a href="#/tasks">查看全部任务</a></div><p className="muted">受理不等于采集完成，进度 100% 不代表成功；失败或部分成功以后端消息、错误与数据覆盖为准。</p><ResourceStatus resource={taskResource} /><div className="table-wrap"><table><thead><tr><th>任务 / 编号</th><th>后端状态</th><th>消息 / 错误</th></tr></thead><tbody>{tasks.map(task => <tr key={task.id}><td>{task.kind === 'catalogue' ? '目录同步' : '份额更新'}<small>{task.id}</small></td><td><Badge value={task.status} /><small>服务返回：{task.status}</small>{!taskResource.data?.items.some(item => item.id === task.id) && <small>列表尚未返回此任务；当前为提交响应，不推断终态</small>}</td><td>{task.message || '暂无后端进度消息'}{task.errors?.map((error, index) => <small className="warn-text" key={index}>{error}</small>)}</td></tr>)}</tbody></table></div></section>}
    <p className="muted"><a href="#/history">查询纯份额历史</a> · <a href="#/watchlist">独立观察池管理</a></p>
  </>;
}
