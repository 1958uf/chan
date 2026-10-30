import type {
  Analysis, Alert, ApiMode, CatalogueCoverage, CatalogueParams, CatalogueResponse, ClassificationRequest, ClassificationStatus,
  Dashboard, ETF, ETFDetail, ETFInput, ExportSharesParams, GroupSummary, Health, HistoryItem, HolderRecord, ListResponse,
  Quality, Settings, SettingsUpdate, ShareGroupParams, ShareGroupResponse, ShareGroupSummary, ShareItem, SharePeriod,
  SharesCoverage, SharesHistoryItem, SharesHistoryParams, SharesHistoryResponse, SharesOverview, SharesOverviewParams, Task, TaskRequest,
} from './types';

type UnknownObject = Record<string, unknown>;
/** 功能：约束对象输入；输入：未知 JSON；输出：安全可读取对象。 */
function object(value: unknown): UnknownObject { return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as UnknownObject : {}; }
/** 功能：保留有限数字，缺失不归零；输入：未知字段；输出：数字或空值。 */
export function nullableNumber(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
/** 功能：标准化分析字段；输入：REST 分析对象；输出：稳定分析类型。 */
export function transformAnalysis(value: unknown): Analysis {
  const raw = object(value);
  return {
    latest_shares: nullableNumber(raw.latest_shares), share_date: typeof raw.share_date === 'string' ? raw.share_date : null,
    delta_shares: nullableNumber(raw.delta_shares), delta_pct: nullableNumber(raw.delta_pct),
    estimated_flow: nullableNumber(raw.estimated_flow), flow_5d: nullableNumber(raw.flow_5d), flow_20d: nullableNumber(raw.flow_20d),
    price: nullableNumber(raw.price), quote_time: typeof raw.quote_time === 'string' ? raw.quote_time : null,
    price_time: typeof raw.price_time === 'string' ? raw.price_time : null,
    premium_pct: nullableNumber(raw.premium_pct), quality: typeof raw.quality === 'string' ? raw.quality as Analysis['quality'] : 'unknown',
    score: nullableNumber(raw.score), coverage: nullableNumber(raw.coverage), label: typeof raw.label === 'string' ? raw.label : '证据不足',
    indicators: Array.isArray(raw.indicators) ? raw.indicators as Analysis['indicators'] : [],
    intraday_indicators: Array.isArray(raw.intraday_indicators) ? raw.intraday_indicators as Analysis['indicators'] : [],
    quote_age_seconds: nullableNumber(raw.quote_age_seconds),
    history: Array.isArray(raw.history) ? raw.history as HistoryItem[] : [],
  };
}
/** 功能：解码分组样本字段，缺质量不推断有效；输入：REST 分组对象；输出：稳定分组数据。 */
export function transformGroup(value: unknown): GroupSummary {
  const raw = object(value);
  const count = nullableNumber(raw.count);
  const coverage = nullableNumber(raw.coverage);
  return {
    group: typeof raw.group === 'string' ? raw.group : '未知分组', flow: nullableNumber(raw.flow),
    count: count != null && Number.isInteger(count) && count >= 0 ? count : undefined,
    coverage: coverage != null && Number.isInteger(coverage) && coverage >= 0 && (count == null || coverage <= count) ? coverage : null,
    ...(typeof raw.quality === 'string' ? { quality: raw.quality as GroupSummary['quality'] } : {}),
  };
}
/** 功能：读取文本字段；输入：未知字段与缺省提示；输出：文本，不将未知日期伪造为今天。 */
function text(value: unknown, fallback = ''): string { return typeof value === 'string' ? value : fallback; }
/** 功能：读取可空文本；输入：未知字段；输出：文本或空值。 */
function nullableText(value: unknown): string | null { return typeof value === 'string' ? value : null; }
/** 功能：保留合法非负计数；输入：未知字段；输出：整数或空值，缺失不归零。 */
function nullableCount(value: unknown): number | null {
  const count = nullableNumber(value);
  return count !== null && Number.isInteger(count) && count >= 0 ? count : null;
}
/** 功能：保留明确布尔值；输入：未知字段；输出：布尔或空值，未知不推断日历完整。 */
function nullableBoolean(value: unknown): boolean | null { return typeof value === 'boolean' ? value : null; }
/** 功能：校验质量枚举；输入：未知质量字段；输出：契约质量或未知。 */
function quality(value: unknown): Quality {
  return ['valid', 'partial', 'stale', 'suspect', 'missing', 'error', 'demo'].includes(text(value)) ? value as Quality : 'unknown';
}
/** 功能：保留明确模式；输入：未知模式字段；输出：真实、演示或未知，不默认真实。 */
function mode(value: unknown): ApiMode { return value === 'live' || value === 'demo' ? value : 'unknown'; }
/** 功能：校验份额统计周期；输入：未知周期字段；输出：日周月或未知。 */
function period(value: unknown): SharePeriod | 'unknown' { return value === 'day' || value === 'week' || value === 'month' ? value : 'unknown'; }
/** 功能：校验分类状态；输入：未知字段；输出：已确认、候选、未分类或未知。 */
function classificationStatus(value: unknown): ClassificationStatus {
  return value === 'confirmed' || value === 'candidate' || value === 'unclassified' ? value : 'unknown';
}
/** 功能：解码目录分类且兼容旧ETF；输入：未知ETF对象；输出：保留可选分类字段的ETF。 */
export function transformETF(value: unknown): ETF {
  const raw = object(value);
  // 六位代码和交易所是身份字段：非法身份直接报错，不能补成上海或启用标的。
  if (!/^[0-9]{6}$/.test(text(raw.code)) || (raw.exchange !== 'sh' && raw.exchange !== 'sz')) throw new ApiError(0, 'API 返回无效的 ETF 代码或交易所');
  return {
    code: raw.code as string, name: text(raw.name), group: text(raw.group, '未知分组'), exchange: raw.exchange,
    enabled: raw.enabled === true, tags: Array.isArray(raw.tags) ? raw.tags.filter((tag): tag is string => typeof tag === 'string') : [],
    ...(raw.listed_on !== undefined ? { listed_on: nullableText(raw.listed_on) } : {}),
    ...(raw.asset_class !== undefined ? { asset_class: text(raw.asset_class, '未分类') } : {}),
    ...(raw.manager !== undefined ? { manager: nullableText(raw.manager) } : {}),
    ...(raw.tracking_index !== undefined ? { tracking_index: nullableText(raw.tracking_index) } : {}),
    ...(raw.classification_status !== undefined ? { classification_status: classificationStatus(raw.classification_status) } : {}),
    ...(raw.classification_evidence !== undefined ? { classification_evidence: text(raw.classification_evidence) } : {}),
    ...(raw.catalogue_source !== undefined ? { catalogue_source: nullableText(raw.catalogue_source) } : {}),
    ...(raw.discovered_at !== undefined ? { discovered_at: nullableText(raw.discovered_at) } : {}),
    ...(typeof raw.manual_classification === 'boolean' ? { manual_classification: raw.manual_classification } : {}),
  };
}
/** 功能：解码纯份额产品统计；输入：REST产品对象；输出：缺值为空、质量与分类未知不冒充有效的产品指标。 */
export function transformShareItem(value: unknown): ShareItem {
  const raw = object(value);
  return {
    code: text(raw.code), name: text(raw.name), group: text(raw.group, '未知分组'), asset_class: text(raw.asset_class, '未分类'),
    shares: nullableNumber(raw.shares), trade_date: nullableText(raw.trade_date), delta_shares: nullableNumber(raw.delta_shares),
    delta_pct: nullableNumber(raw.delta_pct), delta_5d: nullableNumber(raw.delta_5d), delta_20d: nullableNumber(raw.delta_20d),
    increase_streak: nullableCount(raw.increase_streak), decrease_streak: nullableCount(raw.decrease_streak),
    quality: quality(raw.quality), reason: text(raw.reason), source: text(raw.source), classification_status: classificationStatus(raw.classification_status),
    ...(raw.baseline_date !== undefined ? { baseline_date: nullableText(raw.baseline_date) } : {}),
    ...(raw.delta_5d_pct !== undefined ? { delta_5d_pct: nullableNumber(raw.delta_5d_pct) } : {}),
    ...(raw.delta_20d_pct !== undefined ? { delta_20d_pct: nullableNumber(raw.delta_20d_pct) } : {}),
    ...(raw.quality_5d !== undefined ? { quality_5d: quality(raw.quality_5d) } : {}),
    ...(raw.quality_20d !== undefined ? { quality_20d: quality(raw.quality_20d) } : {}),
    ...(raw.reason_5d !== undefined ? { reason_5d: text(raw.reason_5d) } : {}),
    ...(raw.reason_20d !== undefined ? { reason_20d: text(raw.reason_20d) } : {}),
    ...(raw.new_member !== undefined ? { new_member: nullableBoolean(raw.new_member) } : {}),
  };
}
/** 功能：解码同日分组指标；输入：REST分组对象；输出：保留可比集合及分类分母的分组统计。 */
export function transformShareGroup(value: unknown): ShareGroupSummary {
  const raw = object(value);
  return {
    group: text(raw.group, '未知分组'), asset_class: text(raw.asset_class, '未分类'), total_shares: nullableNumber(raw.total_shares),
    delta_shares: nullableNumber(raw.delta_shares), delta_pct: nullableNumber(raw.delta_pct), increased: nullableCount(raw.increased),
    decreased: nullableCount(raw.decreased), unchanged: nullableCount(raw.unchanged), missing_count: nullableCount(raw.missing_count),
    candidate_count: nullableCount(raw.candidate_count), total_count: nullableCount(raw.total_count), available_count: nullableCount(raw.available_count),
    comparable_count: nullableCount(raw.comparable_count), coverage_pct: nullableNumber(raw.coverage_pct), trade_date: nullableText(raw.trade_date), quality: quality(raw.quality),
    ...(raw.unclassified_count !== undefined ? { unclassified_count: nullableCount(raw.unclassified_count) } : {}),
    ...(raw.new_count !== undefined ? { new_count: nullableCount(raw.new_count) } : {}),
    ...(raw.exited_count !== undefined ? { exited_count: nullableCount(raw.exited_count) } : {}),
    ...(raw.availability_pct !== undefined ? { availability_pct: nullableNumber(raw.availability_pct) } : {}),
  };
}
/** 功能：解码份额覆盖并保留扩展元数据；输入：未知覆盖对象；输出：缺值为空的覆盖计数。 */
function transformSharesCoverage(value: unknown): SharesCoverage {
  const raw = object(value);
  return {
    ...raw, total_count: nullableCount(raw.total_count), available_count: nullableCount(raw.available_count), comparable_count: nullableCount(raw.comparable_count),
    missing_count: nullableCount(raw.missing_count), candidate_count: nullableCount(raw.candidate_count), coverage_pct: nullableNumber(raw.coverage_pct),
    ...(raw.unclassified_count !== undefined ? { unclassified_count: nullableCount(raw.unclassified_count) } : {}),
    ...(raw.availability_pct !== undefined ? { availability_pct: nullableNumber(raw.availability_pct) } : {}),
    ...(raw.trade_date !== undefined ? { trade_date: nullableText(raw.trade_date) } : {}),
    ...(raw.baseline_date !== undefined ? { baseline_date: nullableText(raw.baseline_date) } : {}),
    ...(raw.calendar_available !== undefined ? { calendar_available: nullableBoolean(raw.calendar_available) } : {}),
    ...(raw.calendar_complete !== undefined ? { calendar_complete: nullableBoolean(raw.calendar_complete) } : {}),
  };
}
/** 功能：解码份额历史期末存量；输入：REST历史行；输出：无价格净值依赖的历史指标。 */
export function transformSharesHistoryItem(value: unknown): SharesHistoryItem {
  const raw = object(value);
  return {
    date: text(raw.date), group: text(raw.group, '未知分组'), ...(typeof raw.code === 'string' ? { code: raw.code } : {}),
    ...(typeof raw.name === 'string' ? { name: raw.name } : {}), ...(typeof raw.asset_class === 'string' ? { asset_class: raw.asset_class } : {}),
    ...(raw.shares !== undefined ? { shares: nullableNumber(raw.shares) } : {}),
    ...(typeof raw.reason === 'string' ? { reason: raw.reason } : {}), ...(typeof raw.source === 'string' ? { source: raw.source } : {}),
    ...(raw.baseline_date !== undefined ? { baseline_date: nullableText(raw.baseline_date) } : {}),
    ...(raw.trade_date !== undefined ? { trade_date: nullableText(raw.trade_date) } : {}),
    ...(raw.availability_pct !== undefined ? { availability_pct: nullableNumber(raw.availability_pct) } : {}),
    ...Object.fromEntries(['available_count', 'candidate_count', 'unclassified_count', 'missing_count', 'new_count', 'exited_count', 'increased', 'decreased', 'unchanged']
      .filter(key => raw[key] !== undefined).map(key => [key, nullableCount(raw[key])])),
    total_shares: nullableNumber(raw.total_shares), delta_shares: nullableNumber(raw.delta_shares), delta_pct: nullableNumber(raw.delta_pct),
    comparable_count: nullableCount(raw.comparable_count), total_count: nullableCount(raw.total_count), coverage_pct: nullableNumber(raw.coverage_pct), quality: quality(raw.quality),
  };
}
/** 功能：拼接有限查询条件；输入：查询键值；输出：查询字符串，保留合法的零偏移。 */
function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') search.set(key, String(value)); });
  return search.size ? `?${search}` : '';
}
/** 功能：表达接口失败；输入：状态与提示；输出：可展示的异常。 */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = 'ApiError'; }
}
/** 功能：封装同源 REST 和会话鉴权；输入：API 根路径；输出：稳定客户端。 */
export class ApiClient {
  private token: string | null = null;
  private tokenPromise: Promise<string> | null = null;
  constructor(private readonly base = '/api') {}

  /** 功能：从服务端获得会话令牌，不持久化敏感信息；输入：无；输出：令牌。 */
  private async session(): Promise<string> {
    if (this.token) return this.token;
    if (!this.tokenPromise) this.tokenPromise = this.request<{ token: string }>('/session').then(data => {
      if (!data.token) throw new ApiError(401, '服务端未返回会话令牌，无法执行变更');
      this.token = data.token; return data.token;
    }).finally(() => { this.tokenPromise = null; });
    return this.tokenPromise;
  }

  /** 功能：发起有超时的 JSON 请求，变更自动鉴权；输入：路径、选项；输出：契约数据。 */
  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const method = options.method || 'GET';
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (options.body) headers.set('Content-Type', 'application/json');
    if (!['GET', 'HEAD'].includes(method)) headers.set('X-ETF-Token', await this.session());
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(`${this.base}${path}`, { ...options, headers, signal: controller.signal, credentials: 'same-origin' });
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) this.token = null;
        let detail = `请求失败（HTTP ${response.status}）`;
        try {
          const payload = object(await response.json());
          if (typeof payload.detail === 'string') detail = payload.detail;
          else if (Array.isArray(payload.detail)) detail = payload.detail.map(item => { const entry = object(item); return `${Array.isArray(entry.loc) ? entry.loc.join('.') : '参数'}：${String(entry.msg || '无效')}`; }).join('；');
          else if (typeof payload.message === 'string') detail = payload.message;
        } catch { /* 非 JSON 错误页沿用 HTTP 提示，不假报成功。 */ }
        throw new ApiError(response.status, detail);
      }
      return await response.json() as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, error instanceof DOMException && error.name === 'AbortError' ? '请求超时，请检查后端与数据源状态' : '无法连接 API，请检查独立后端是否启动');
    } finally { window.clearTimeout(timer); }
  }

  /** 功能：读取健康状态；输入：无；输出：健康信息。 */
  health(): Promise<Health> { return this.request('/health'); }
  /** 功能：读取并标准化仪表盘；输入：无；输出：仪表盘。 */
  async dashboard(): Promise<Dashboard> {
    const data = await this.request<Dashboard>('/dashboard');
    return { ...data, etfs: (data.etfs || []).map(item => ({ ...item, ...transformAnalysis(item) })), groups: (data.groups || []).map(transformGroup), market: data.market || [] };
  }
  /** 功能：读取观察池；输入：无；输出：ETF 列表。 */
  etfs(): Promise<ListResponse<ETF>> { return this.request('/etfs'); }
  /** 功能：新建或更新观察标的；输入：兼容旧观察池的ETF；输出：保存记录，目录新增字段不写入此接口。 */
  saveETF(etf: ETFInput): Promise<ETF> {
    const { code, name, group, exchange, enabled, listed_on, tags } = etf;
    return this.request('/etfs', { method: 'POST', body: JSON.stringify({ code, name, group, exchange, enabled, listed_on, tags }) });
  }
  /** 功能：读取并解码纯份额首页；输入：截止日、周期及资产分组筛选；输出：份额、覆盖和真实模式信息。 */
  async sharesOverview(params: SharesOverviewParams = {}): Promise<SharesOverview> {
    const raw = object(await this.request<unknown>(`/shares/overview${query({ ...params })}`));
    return {
      as_of: text(raw.as_of), ...(raw.period !== undefined ? { period: period(raw.period) } : {}),
      ...(raw.statistics_date !== undefined ? { statistics_date: nullableText(raw.statistics_date) } : {}),
      requested_as_of: text(raw.requested_as_of || raw.as_of), date_selection: text(raw.date_selection),
      items: Array.isArray(raw.items) ? raw.items.map(transformShareItem) : [],
      groups: Array.isArray(raw.groups) ? raw.groups.map(transformShareGroup) : [],
      coverage: transformSharesCoverage(raw.coverage), mode: mode(raw.mode), notice: text(raw.notice),
    };
  }
  /** 功能：读取类别内全部产品份额；输入：分组及截止日、周期；输出：同日分组统计与成员。 */
  async shareGroup(group: string, params: ShareGroupParams = {}): Promise<ShareGroupResponse> {
    const raw = object(await this.request<unknown>(`/shares/groups/${encodeURIComponent(group)}${query({ ...params })}`));
    return { group: transformShareGroup(raw.group), items: Array.isArray(raw.items) ? raw.items.map(transformShareItem) : [], mode: mode(raw.mode), notice: text(raw.notice) };
  }
  /** 功能：读取日周月份额历史；输入：日期范围、频率及分组代码；输出：已解码期末存量序列。 */
  async sharesHistory(params: SharesHistoryParams = {}): Promise<SharesHistoryResponse> {
    const raw = object(await this.request<unknown>(`/shares/history${query({ ...params })}`));
    return {
      items: Array.isArray(raw.items) ? raw.items.map(transformSharesHistoryItem) : [], mode: mode(raw.mode), frequency: period(raw.frequency), notice: text(raw.notice),
      ...(raw.total !== undefined ? { total: nullableCount(raw.total) } : {}),
      ...(raw.calendar_complete !== undefined ? { calendar_complete: nullableBoolean(raw.calendar_complete) } : {}),
    };
  }
  /** 功能：分页查询完整ETF目录；输入：资产、分组、分类状态、检索词及分页；输出：目录与来源覆盖。 */
  async catalogue(params: CatalogueParams = {}): Promise<CatalogueResponse> {
    const raw = object(await this.request<unknown>(`/catalogue${query({ ...params })}`));
    const coverage = object(raw.coverage);
    const decodedCoverage: CatalogueCoverage = {
      ...coverage,
      sources: Array.isArray(coverage.sources) ? coverage.sources : Object.fromEntries(Object.entries(object(coverage.sources)).map(([source, count]) => [source, nullableCount(count)])),
      ...Object.fromEntries(['confirmed', 'candidate', 'unclassified', 'enabled'].filter(key => coverage[key] !== undefined).map(key => [key, nullableCount(coverage[key])])),
      ...(coverage.notice !== undefined ? { notice: text(coverage.notice) } : {}),
    };
    return {
      items: Array.isArray(raw.items) ? raw.items.map(transformETF) : [], total: nullableCount(raw.total), coverage: decodedCoverage,
      ...(raw.mode !== undefined ? { mode: mode(raw.mode) } : {}), ...(typeof raw.notice === 'string' ? { notice: raw.notice } : {}),
    };
  }
  /** 功能：人工确认目录分类且沿用会话鉴权；输入：严格分类请求；输出：保存后的ETF目录记录。 */
  async classifyETF(request: ClassificationRequest): Promise<ETF> {
    const { code, group, asset_class, tracking_index, classification_status, enabled } = request;
    return transformETF(await this.request<unknown>('/catalogue/classify', {
      method: 'POST', body: JSON.stringify({ code, group, asset_class, tracking_index, classification_status, enabled }),
    }));
  }
  /** 功能：读取并标准化标的详情；输入：六位代码；输出：详情。 */
  async detail(code: string): Promise<ETFDetail> {
    const data = await this.request<ETFDetail>(`/etfs/${encodeURIComponent(code)}`);
    return { ...data, analysis: transformAnalysis(data.analysis), shares: data.shares || [], quotes: data.quotes || [], bars: data.bars || [], navs: data.navs || [], holders: data.holders || [] };
  }
  /** 功能：读取历史流量；输入：分组和日期；输出：历史记录。 */
  history(params: { group?: string; start?: string; end?: string } = {}): Promise<ListResponse<HistoryItem>> { return this.request(`/history${query(params)}`); }
  /** 功能：读取持有人；输入：可选代码；输出：报告期记录。 */
  holders(code?: string): Promise<ListResponse<HolderRecord>> { return this.request(`/holders${query({ code })}`); }
  /** 功能：人工导入持有人报告；输入：严格记录数组；输出：后端结果。 */
  importHolders(records: HolderRecord[]): Promise<unknown> { return this.request('/holders/import', { method: 'POST', body: JSON.stringify({ records }) }); }
  /** 功能：读取告警；输入：无；输出：告警列表。 */
  alerts(): Promise<ListResponse<Alert>> { return this.request('/alerts'); }
  /** 功能：确认告警；输入：告警编号；输出：确认结果。 */
  acknowledge(id: string | number): Promise<{ ok: boolean }> { return this.request(`/alerts/${encodeURIComponent(id)}/ack`, { method: 'POST' }); }
  /** 功能：读取任务；输入：无；输出：任务列表。 */
  tasks(): Promise<ListResponse<Task>> { return this.request('/tasks'); }
  /** 功能：建立采集任务；输入：类型和可选范围；输出：任务。 */
  createTask(request: TaskRequest): Promise<Task> { return this.request('/tasks', { method: 'POST', body: JSON.stringify(request) }); }
  /** 功能：请求取消任务；输入：任务编号；输出：受理结果。 */
  cancelTask(id: string): Promise<{ ok: boolean }> { return this.request(`/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' }); }
  /** 功能：读取非敏感配置；输入：无；输出：配置。 */
  settings(): Promise<Settings> { return this.request('/settings'); }
  /** 功能：保存白名单配置；输入：阈值和调度；输出：服务端配置。 */
  saveSettings(settings: SettingsUpdate): Promise<Settings> { return this.request('/settings', { method: 'PUT', body: JSON.stringify(settings) }); }
  /** 功能：下载纯份额概览且失败不产生空文件；输入：格式、截止日、周期和分组；输出：服务端CSV或JSON文件Blob。 */
  async exportShares(format: 'csv' | 'json', params: ExportSharesParams = {}): Promise<Blob> {
    try {
      const response = await fetch(`${this.base}/shares/export${query({ ...params, format })}`, {
        credentials: 'same-origin', signal: AbortSignal.timeout(25000),
      });
      if (!response.ok) throw new ApiError(response.status, `份额导出失败（HTTP ${response.status}）`);
      return await response.blob();
    } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(0, '份额导出连接失败或超时'); }
  }
  /** 功能：下载服务端导出，失败不触发空文件；输入：格式与范围；输出：文件 Blob。 */
  async exportData(format: 'csv' | 'json', params: { code?: string; start?: string; end?: string } = {}): Promise<Blob> {
    try {
      const response = await fetch(`${this.base}/export${query({ ...params, format })}`, { credentials: 'same-origin', signal: AbortSignal.timeout(25000) });
      if (!response.ok) throw new ApiError(response.status, `导出失败（HTTP ${response.status}）`);
      return await response.blob();
    } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError(0, '导出连接失败或超时'); }
  }
}
export const api = new ApiClient();
