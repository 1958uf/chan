import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, nullableNumber, transformAnalysis, transformETF, transformGroup, transformShareGroup, transformShareItem, transformSharesHistoryItem } from '../src/api/client';
import type { ETF, TaskRequest } from '../src/api/types';

/** 功能：建立 JSON 响应；输入：JSON 数据与状态；输出：Fetch 响应。 */
function json(data: unknown, status = 200): Response { return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }); }

describe('稳定 REST 客户端', () => {
  it('缺值、无穷和字符串数值不转为零，指标缺失为未知', () => {
    expect(nullableNumber(undefined)).toBeNull(); expect(nullableNumber(Infinity)).toBeNull(); expect(nullableNumber('1')).toBeNull(); expect(nullableNumber(0)).toBe(0);
    const transformed = transformAnalysis({ score: null, price: 0, estimated_flow: null });
    expect(transformed.quality).toBe('unknown'); expect(transformed.latest_shares).toBeNull(); expect(transformed.indicators).toEqual([]); expect(transformed.score).toBeNull();
  });
  it('可选盘中指标与行情年龄兼容旧接口，独立解码不重算日评分', () => {
    const item = { name: '盘中量价线索（估算）', value: 1.2, state: 'unknown', explanation: '线性进度估算，不纳入日评分', quality: 'partial' };
    const decoded = transformAnalysis({ score: 50, indicators: [], intraday_indicators: [item], quote_age_seconds: 30 });
    expect(decoded.intraday_indicators).toEqual([item]); expect(decoded.quote_age_seconds).toBe(30); expect(decoded.score).toBe(50); expect(decoded.indicators).toEqual([]);
    const legacy = transformAnalysis({ score: 40 }); expect(legacy.intraday_indicators).toEqual([]); expect(legacy.quote_age_seconds).toBeNull(); expect(legacy.score).toBe(40);
    expect(transformAnalysis({ quote_age_seconds: Infinity }).quote_age_seconds).toBeNull();
  });
  it('真实分组字段按样本数量解码，缺 quality 不编造质量，覆盖异常保持未知', () => {
    expect(transformGroup({ group: '沪深300', flow: 8834000, count: 4, coverage: 4 })).toEqual({ group: '沪深300', flow: 8834000, count: 4, coverage: 4 });
    expect(transformGroup({ group: '空组', count: 2, coverage: 3 }).coverage).toBeNull();
    expect(transformGroup({ group: '空组', count: 2 }).flow).toBeNull();
    expect(transformGroup({ group: '空组', count: 2 })).not.toHaveProperty('quality');
  });
  it('所有变更自动先获取 session token，不发令牌给 GET', async () => {
    const mock = vi.fn().mockResolvedValueOnce(json({ token: 'local-session' })).mockResolvedValueOnce(json({ ok: true })).mockResolvedValueOnce(json({ id: 'task' }));
    vi.stubGlobal('fetch', mock);
    const client = new ApiClient(); await client.acknowledge('a/b'); await client.createTask({ kind: 'refresh' });
    expect(mock.mock.calls.map(call => call[0])).toEqual(['/api/session', '/api/alerts/a%2Fb/ack', '/api/tasks']);
    expect(new Headers(mock.mock.calls[0][1].headers).has('X-ETF-Token')).toBe(false);
    expect(new Headers(mock.mock.calls[1][1].headers).get('X-ETF-Token')).toBe('local-session');
    expect(new Headers(mock.mock.calls[2][1].headers).get('X-ETF-Token')).toBe('local-session');
  });
  it('并发变更共享一次 token 请求', async () => {
    const mock = vi.fn(async (url: string) => json(url.endsWith('/session') ? { token: 'shared' } : { ok: true }));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    await Promise.all([client.acknowledge(1), client.cancelTask('task')]);
    expect(mock.mock.calls.filter(call => call[0].endsWith('/session'))).toHaveLength(1);
  });
  it('权限失败可见且下次操作重新取 session，不自动重放变更', async () => {
    const mock = vi.fn().mockResolvedValueOnce(json({ token: 'old' })).mockResolvedValueOnce(json({ detail: '令牌无效' }, 403)).mockResolvedValueOnce(json({ token: 'new' })).mockResolvedValueOnce(json({ ok: true }));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    await expect(client.acknowledge(1)).rejects.toThrow('令牌无效'); await client.acknowledge(1);
    expect(mock).toHaveBeenCalledTimes(4);
    expect(new Headers(mock.mock.calls[3][1].headers).get('X-ETF-Token')).toBe('new');
  });
  it('后端参数校验错误保留字段说明', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({ token: 't' })).mockResolvedValueOnce(json({ detail: [{ loc: ['body', 'code'], msg: '六位数字' }] }, 422)));
    await expect(new ApiClient().saveETF({ code: 'bad', name: '测试', group: '测试', exchange: 'sh', enabled: true, tags: [] })).rejects.toThrow('body.code：六位数字');
  });
  it('真实接口空返回保留空列表，不注入演示', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ mode: 'live', etfs: [], groups: [], market: [], notice: '', as_of: '' })));
    expect((await new ApiClient().dashboard()).etfs).toEqual([]);
  });
  it('网络失败、非 JSON HTTP 失败与导出失败明确抛错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));
    await expect(new ApiClient().health()).rejects.toThrow('无法连接 API');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('bad gateway', { status: 502 })));
    await expect(new ApiClient().health()).rejects.toBeInstanceOf(ApiError);
    await expect(new ApiClient().exportData('csv')).rejects.toThrow('导出失败');
  });
  it('导出参数正确编码且返回真正 blob', async () => {
    const mock = vi.fn().mockResolvedValue(new Response('code,shares\n510300,1', { status: 200 })); vi.stubGlobal('fetch', mock);
    const blob = await new ApiClient().exportData('csv', { code: '510300', start: '2026-10-01' });
    expect(mock.mock.calls[0][0]).toBe('/api/export?code=510300&start=2026-10-01&format=csv'); expect(blob.size).toBeGreaterThan(0);
  });
});

describe('纯份额及目录 REST 契约', () => {
  it('产品份额解码保留零和负增量，但缺失、非有限、字符串不归零', () => {
    const decoded = transformShareItem({ code: '510300', shares: 0, delta_shares: -12, delta_pct: null, delta_5d: '5', delta_20d: Infinity, increase_streak: 0, decrease_streak: 2, quality: 'partial', classification_status: 'candidate' });
    expect(decoded).toMatchObject({ code: '510300', shares: 0, delta_shares: -12, delta_pct: null, delta_5d: null, delta_20d: null, increase_streak: 0, decrease_streak: 2, trade_date: null, quality: 'partial', classification_status: 'candidate' });
    const missing = transformShareItem(undefined);
    for (const key of ['shares', 'delta_shares', 'delta_pct', 'delta_5d', 'delta_20d', 'increase_streak', 'decrease_streak'] as const) expect(missing[key]).toBeNull();
    expect(missing.quality).toBe('unknown'); expect(missing.classification_status).toBe('unknown');
    expect(transformShareItem({ quality: 'future', classification_status: 'future', increase_streak: -1, decrease_streak: 1.5 })).toMatchObject({ quality: 'unknown', classification_status: 'unknown', increase_streak: null, decrease_streak: null });
  });
  it('分组可比与分类分母独立解码，缺计数不假零也不重算覆盖', () => {
    const group = transformShareGroup({ group: '沪深300', total_shares: 1000, delta_shares: -50, increased: 0, decreased: 2, unchanged: 1, total_count: 6, available_count: 3, comparable_count: 2, missing_count: 3, candidate_count: 1, coverage_pct: 50, trade_date: '2026-10-28', quality: 'partial' });
    expect(group).toMatchObject({ total_shares: 1000, delta_shares: -50, increased: 0, total_count: 6, available_count: 3, comparable_count: 2, coverage_pct: 50, quality: 'partial', trade_date: '2026-10-28' });
    expect(group.delta_pct).toBeNull();
    const missing = transformShareGroup({ total_count: '6', available_count: -1, comparable_count: 1.5, coverage_pct: NaN });
    for (const key of ['total_shares', 'delta_shares', 'delta_pct', 'total_count', 'available_count', 'comparable_count', 'coverage_pct', 'increased', 'missing_count', 'candidate_count'] as const) expect(missing[key]).toBeNull();
    expect(missing.quality).toBe('unknown'); expect(missing.trade_date).toBeNull();
  });
  it('份额历史解码保留期末存量，缺字段不相加或冒充有效', () => {
    expect(transformSharesHistoryItem({ date: '2026-10-23', group: '沪深300', code: '510300', total_shares: 400, delta_shares: 0, comparable_count: 0, total_count: 2, coverage_pct: 0, quality: 'missing' })).toMatchObject({ date: '2026-10-23', code: '510300', total_shares: 400, delta_shares: 0, delta_pct: null, comparable_count: 0, total_count: 2, coverage_pct: 0, quality: 'missing' });
    expect(transformSharesHistoryItem({ total_shares: '400', delta_shares: -Infinity })).toMatchObject({ total_shares: null, delta_shares: null, comparable_count: null, total_count: null, coverage_pct: null, quality: 'unknown' });
  });
  it('首页、分组和历史使用新路由及编码筛选，GET保持同源且不索取token', async () => {
    const mock = vi.fn()
      .mockResolvedValueOnce(json({ as_of: '2026-10-28', period: 'week', items: [{ code: '510300', shares: null, delta_shares: 0 }], groups: [{ group: '沪深300', total_count: 2 }], coverage: { total_count: 2, available_count: 0, coverage_pct: 0, calendar_covered: false }, mode: 'demo', notice: '演示' }))
      .mockResolvedValueOnce(json({ group: { group: '沪深/300', trade_date: '2026-10-28' }, items: [], mode: 'live', notice: '日份额' }))
      .mockResolvedValueOnce(json({ items: [{ date: '2026-10-23', total_shares: 300 }], mode: 'live', frequency: 'month', notice: '期末存量' }));
    vi.stubGlobal('fetch', mock); const client = new ApiClient('/custom/api');
    const overview = await client.sharesOverview({ as_of: '2026-10-28', period: 'week', asset_class: '宽基', group: '沪深300' });
    const group = await client.shareGroup('沪深/300', { as_of: '2026-10-28', period: 'day' });
    const history = await client.sharesHistory({ start: '2026-10-01', end: '2026-10-28', frequency: 'month', group: '沪深300', code: '510300' });
    expect(mock.mock.calls.map(call => call[0])).toEqual([
      `/custom/api/shares/overview?as_of=2026-10-28&period=week&asset_class=${encodeURIComponent('宽基')}&group=${encodeURIComponent('沪深300')}`,
      `/custom/api/shares/groups/${encodeURIComponent('沪深/300')}?as_of=2026-10-28&period=day`,
      `/custom/api/shares/history?start=2026-10-01&end=2026-10-28&frequency=month&group=${encodeURIComponent('沪深300')}&code=510300`,
    ]);
    expect(overview).toMatchObject({ mode: 'demo', period: 'week', coverage: { total_count: 2, available_count: 0, comparable_count: null, coverage_pct: 0, calendar_covered: false } });
    expect(overview.items[0]).toMatchObject({ shares: null, delta_shares: 0, quality: 'unknown' });
    expect(group).toMatchObject({ mode: 'live', group: { trade_date: '2026-10-28', total_shares: null }, items: [] });
    expect(history).toMatchObject({ mode: 'live', frequency: 'month', items: [{ total_shares: 300, delta_shares: null }] });
    for (const [, options] of mock.mock.calls) {
      expect(options.credentials).toBe('same-origin'); expect(new Headers(options.headers).has('X-ETF-Token')).toBe(false);
      expect(new Headers(options.headers).has('Origin')).toBe(false);
    }
  });
  it('未知或缺失mode和frequency不假live或day，空列表不注入演示', async () => {
    const mock = vi.fn().mockResolvedValueOnce(json({ mode: 'future', items: [], groups: [] })).mockResolvedValueOnce(json({ items: null })).mockResolvedValueOnce(json({ frequency: 'future' }));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    expect(await client.sharesOverview()).toMatchObject({ mode: 'unknown', items: [], groups: [], coverage: { total_count: null, available_count: null, coverage_pct: null } });
    expect(await client.shareGroup('测试')).toMatchObject({ mode: 'unknown', items: [], group: { total_shares: null, quality: 'unknown' } });
    expect(await client.sharesHistory()).toMatchObject({ mode: 'unknown', frequency: 'unknown', items: [] });
    expect(mock.mock.calls.map(call => call[0])).toEqual(['/api/shares/overview', `/api/shares/groups/${encodeURIComponent('测试')}`, '/api/shares/history']);
  });
  it('目录ETF兼容旧对象，分类字段不推断confirmed，非法身份报错', () => {
    const legacy: ETF = { code: '510300', name: '沪深300ETF', group: '沪深300', exchange: 'sh', enabled: false, tags: [] };
    expect(transformETF(legacy)).toEqual(legacy);
    expect(transformETF({ ...legacy, classification_status: 'future', manager: null, tracking_index: null, manual_classification: false })).toMatchObject({ classification_status: 'unknown', manager: null, tracking_index: null, manual_classification: false });
    expect(() => transformETF({ ...legacy, exchange: 'unknown' })).toThrow('无效的 ETF');
    expect(() => transformETF({ ...legacy, code: 510300 })).toThrow('无效的 ETF');
  });
  it('目录分页保留offset=0和中文检索，来源扩展与分类字段不丢失', async () => {
    const etf = { code: '510300', name: '沪深300ETF', group: '沪深300', exchange: 'sh', enabled: true, tags: [], asset_class: '宽基', manager: '基金公司', tracking_index: '沪深300', classification_status: 'confirmed', classification_evidence: '指数核验', catalogue_source: 'sse', discovered_at: '2026-10-28T09:00:00+08:00', manual_classification: true };
    const mock = vi.fn().mockResolvedValueOnce(json({ items: [etf], total: 1, coverage: { sources: ['sse', 'szse'], confirmed: 1, complete: false }, mode: 'future' })).mockResolvedValueOnce(json({ items: [], coverage: null }));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    const result = await client.catalogue({ asset_class: '宽基', group: '沪深300', classification_status: 'confirmed', q: '300 ETF', limit: 5000, offset: 0 });
    expect(mock.mock.calls[0][0]).toBe(`/api/catalogue?asset_class=${encodeURIComponent('宽基')}&group=${encodeURIComponent('沪深300')}&classification_status=confirmed&q=300+ETF&limit=5000&offset=0`);
    expect(result).toEqual({ items: [etf], total: 1, coverage: { sources: ['sse', 'szse'], confirmed: 1, complete: false }, mode: 'unknown' });
    expect(await client.catalogue()).toEqual({ items: [], total: null, coverage: { sources: {} } });
    expect(mock.mock.calls[1][0]).toBe('/api/catalogue');
  });
  it('人工分类及新任务复用session鉴权与Origin旧机制，不发送额外目录字段', async () => {
    const etf = { code: '510300', name: '沪深300ETF', group: '沪深300', exchange: 'sh', enabled: true, tags: [], asset_class: '宽基', classification_status: 'confirmed', manual_classification: true };
    const mock = vi.fn().mockResolvedValueOnce(json({ token: 'shared' })).mockResolvedValueOnce(json(etf)).mockResolvedValueOnce(json({ id: 'catalogue' })).mockResolvedValueOnce(json({ id: 'shares' }));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    const input = { code: '510300', group: '沪深300', asset_class: '宽基', tracking_index: '沪深300', classification_status: 'confirmed' as const, catalogue_source: '不可写入', manual_classification: false };
    expect(await client.classifyETF(input)).toEqual(etf);
    const catalogueTask: TaskRequest = { kind: 'catalogue' }; const sharesTask: TaskRequest = { kind: 'shares', group: '沪深300', asset_class: '宽基', start: '2026-10-01', end: '2026-10-28', codes: ['510300'] };
    await client.createTask(catalogueTask); await client.createTask(sharesTask);
    expect(mock.mock.calls.map(call => call[0])).toEqual(['/api/session', '/api/catalogue/classify', '/api/tasks', '/api/tasks']);
    expect(JSON.parse(mock.mock.calls[1][1].body)).toEqual({ code: '510300', group: '沪深300', asset_class: '宽基', tracking_index: '沪深300', classification_status: 'confirmed' });
    expect(JSON.parse(mock.mock.calls[2][1].body)).toEqual(catalogueTask); expect(JSON.parse(mock.mock.calls[3][1].body)).toEqual(sharesTask);
    for (const [, options] of mock.mock.calls.slice(1)) {
      expect(new Headers(options.headers).get('X-ETF-Token')).toBe('shared'); expect(new Headers(options.headers).has('Origin')).toBe(false); expect(options.credentials).toBe('same-origin');
    }
  });
  it('saveETF白名单只发旧ETFInput字段，目录新增和任意额外字段不发送', async () => {
    const legacy: ETF = { code: '510300', name: '沪深300ETF', group: '沪深300', exchange: 'sh', enabled: false, tags: ['观察'], listed_on: null };
    const catalogue = { ...legacy, asset_class: '宽基', manager: '公司', tracking_index: '沪深300', classification_status: 'candidate' as const, classification_evidence: '待核验', catalogue_source: 'sse', discovered_at: '2026-10-28T09:00:00+08:00', manual_classification: true, token: '不能泄漏' };
    const mock = vi.fn().mockResolvedValueOnce(json({ token: 't' })).mockResolvedValueOnce(json(legacy)).mockResolvedValueOnce(json(legacy));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    await client.saveETF(catalogue); await client.saveETF({ ...legacy, listed_on: undefined });
    expect(JSON.parse(mock.mock.calls[1][1].body)).toEqual(legacy);
    expect(JSON.parse(mock.mock.calls[2][1].body)).toEqual({ code: legacy.code, name: legacy.name, group: legacy.group, exchange: legacy.exchange, enabled: false, tags: ['观察'] });
    expect(new Headers(mock.mock.calls[1][1].headers).get('X-ETF-Token')).toBe('t');
  });
  it('人工分类权限失败可见、不重放，下次分类重新取token', async () => {
    const etf = { code: '510300', name: '沪深300ETF', group: '沪深300', exchange: 'sh', enabled: true, tags: [] };
    const input = { code: '510300', group: '沪深300', asset_class: '宽基', classification_status: 'confirmed' as const };
    const mock = vi.fn().mockResolvedValueOnce(json({ token: 'old' })).mockResolvedValueOnce(json({ detail: 'Origin无效' }, 403)).mockResolvedValueOnce(json({ token: 'new' })).mockResolvedValueOnce(json(etf));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    await expect(client.classifyETF(input)).rejects.toThrow('Origin无效'); expect(mock).toHaveBeenCalledTimes(2);
    await client.classifyETF(input); expect(mock).toHaveBeenCalledTimes(4);
    expect(new Headers(mock.mock.calls[3][1].headers).get('X-ETF-Token')).toBe('new');
  });
  it('新路由API缺失不演示降级，目录校验错误保留后端说明', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: '接口不存在' }, 404)));
    const client = new ApiClient();
    await expect(client.sharesOverview()).rejects.toMatchObject({ status: 404, message: '接口不存在' });
    await expect(client.shareGroup('沪深300')).rejects.toMatchObject({ status: 404 });
    await expect(client.sharesHistory()).rejects.toMatchObject({ status: 404 });
    await expect(client.catalogue()).rejects.toMatchObject({ status: 404 });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({ token: 't' })).mockResolvedValueOnce(json({ detail: [{ loc: ['body', 'classification_status'], msg: '只能confirmed' }] }, 422)));
    await expect(new ApiClient().classifyETF({ code: '510300', group: '沪深300', asset_class: '宽基', classification_status: 'confirmed' })).rejects.toThrow('body.classification_status：只能confirmed');
  });
  it('份额导出路由编码且返回真实Blob，GET无token和Origin伪造', async () => {
    const mock = vi.fn().mockResolvedValueOnce(new Response('code,delta_shares\n510300,-20')).mockResolvedValueOnce(new Response('{"items":[]}'));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    const blob = await client.exportShares('csv', { as_of: '2026-10-28', period: 'week', group: '沪深/300' });
    expect(blob).toBeInstanceOf(Blob); expect(blob.size).toBe('code,delta_shares\n510300,-20'.length);
    expect(mock.mock.calls[0][0]).toBe(`/api/shares/export?as_of=2026-10-28&period=week&group=${encodeURIComponent('沪深/300')}&format=csv`);
    expect(mock.mock.calls[0][1].credentials).toBe('same-origin'); expect(mock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    expect(new Headers(mock.mock.calls[0][1].headers).has('X-ETF-Token')).toBe(false); expect(new Headers(mock.mock.calls[0][1].headers).has('Origin')).toBe(false);
    await client.exportShares('json'); expect(mock.mock.calls[1][0]).toBe('/api/shares/export?format=json');
  });
  it('真实后端来源数量映射、分类统计和enabled写入按实际模型解码', async () => {
    const etf = { code: '510300', name: '沪深300ETF', group: '沪深300', exchange: 'sh', enabled: false, tags: [], manual_classification: true };
    const mock = vi.fn().mockResolvedValueOnce(json({ items: [], total: 0, coverage: { sources: { sse: 2, szse: null, invalid: '3' }, confirmed: 0, candidate: null, unclassified: '2', enabled: 0, notice: '已发现，不代表全覆盖' } }))
      .mockResolvedValueOnce(json({ token: 't' })).mockResolvedValueOnce(json(etf));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    expect(await client.catalogue()).toEqual({ items: [], total: 0, coverage: { sources: { sse: 2, szse: null, invalid: null }, confirmed: 0, candidate: null, unclassified: null, enabled: 0, notice: '已发现，不代表全覆盖' } });
    await client.classifyETF({ code: '510300', group: '沪深300', asset_class: '宽基', tracking_index: null, classification_status: 'confirmed', enabled: false });
    expect(JSON.parse(mock.mock.calls[2][1].body)).toEqual({ code: '510300', group: '沪深300', asset_class: '宽基', tracking_index: null, classification_status: 'confirmed', enabled: false });
  });
  it('实际份额扩展保留基线、窗口、成员变更和日历信息，非法数值不归零', async () => {
    const mock = vi.fn().mockResolvedValueOnce(json({ items: [{ baseline_date: '2026-10-27', delta_5d_pct: 0, delta_20d_pct: '20', quality_5d: 'partial', quality_20d: 'future', reason_5d: '断档', new_member: false }], groups: [{ unclassified_count: 1, new_count: 0, exited_count: null, availability_pct: 50 }], coverage: { calendar_available: true, calendar_complete: 'true', unclassified_count: 1, availability_pct: 50, baseline_date: null }, mode: 'live' }))
      .mockResolvedValueOnce(json({ items: [{ shares: null, name: '沪深300ETF', asset_class: '宽基', source: 'sse', reason: '缺失', baseline_date: '2026-10-27', trade_date: '2026-10-28', available_count: 0, new_count: null, exited_count: '1', availability_pct: 0 }], total: 0, calendar_complete: false, frequency: 'day', mode: 'live' }));
    vi.stubGlobal('fetch', mock); const client = new ApiClient();
    const overview = await client.sharesOverview();
    expect(overview.items[0]).toMatchObject({ baseline_date: '2026-10-27', delta_5d_pct: 0, delta_20d_pct: null, quality_5d: 'partial', quality_20d: 'unknown', reason_5d: '断档', new_member: false });
    expect(overview.groups[0]).toMatchObject({ unclassified_count: 1, new_count: 0, exited_count: null, availability_pct: 50 });
    expect(overview.coverage).toMatchObject({ calendar_available: true, calendar_complete: null, unclassified_count: 1, availability_pct: 50, baseline_date: null });
    expect(await client.sharesHistory()).toMatchObject({ total: 0, calendar_complete: false, items: [{ shares: null, name: '沪深300ETF', source: 'sse', reason: '缺失', baseline_date: '2026-10-27', available_count: 0, new_count: null, exited_count: null, availability_pct: 0 }] });
    expect(transformSharesHistoryItem({ shares: '5' }).shares).toBeNull();
    expect(transformSharesHistoryItem({})).not.toHaveProperty('shares');
  });
  it('份额导出HTTP、连接和超时失败不会返回空文件', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('bad gateway', { status: 502 })));
    await expect(new ApiClient().exportShares('csv')).rejects.toMatchObject({ status: 502, message: '份额导出失败（HTTP 502）' });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));
    await expect(new ApiClient().exportShares('json')).rejects.toThrow('份额导出连接失败或超时');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('timeout', 'AbortError')));
    await expect(new ApiClient().exportShares('csv')).rejects.toThrow('份额导出连接失败或超时');
  });
});
