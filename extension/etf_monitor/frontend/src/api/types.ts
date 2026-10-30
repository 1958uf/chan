/** REST 类型以 DEVELOPMENT.md 为边界，金额单位元、份额单位份，不将空值转成零。 */
export type Quality = 'valid' | 'partial' | 'stale' | 'suspect' | 'missing' | 'error' | 'demo' | 'unknown';
/** 新接口模式未知时不得视为真实在线。 */
export type ApiMode = 'live' | 'demo' | 'unknown';
export type ClassificationStatus = 'confirmed' | 'candidate' | 'unclassified' | 'unknown';
export interface ETF {
  code: string; name: string; group: string; exchange: 'sh' | 'sz'; enabled: boolean; listed_on?: string | null; tags: string[];
  /** 目录分类字段全部可选，兼容旧观察池对象；未提供不推断已确认。 */
  asset_class?: string; manager?: string | null; tracking_index?: string | null; classification_status?: ClassificationStatus;
  classification_evidence?: string; catalogue_source?: string | null; discovered_at?: string | null; manual_classification?: boolean;
}
/** 旧观察池写入契约：目录分类只能通过独立人工分类接口更新。 */
export type ETFInput = Pick<ETF, 'code' | 'name' | 'group' | 'exchange' | 'enabled' | 'listed_on' | 'tags'>;
export interface RecordMeta { source: string; fetched_at: string; quality: Quality }
export interface ShareRecord extends RecordMeta { code: string; trade_date: string; shares: number }
export interface QuoteRecord extends RecordMeta { code: string; quote_time: string; price: number; previous_close?: number | null; volume?: number | null; amount?: number | null; iopv?: number | null; premium_pct?: number | null }
export interface BarRecord extends RecordMeta { code: string; time: string; interval: 'day' | '1m' | '5m'; open: number; high: number; low: number; close: number; volume?: number | null; amount?: number | null }
export interface NavRecord extends RecordMeta { code: string; trade_date: string; nav: number }
export interface HolderRecord extends RecordMeta { code: string; report_date: string; published_on?: string | null; holder: string; shares?: number | null; ratio_pct?: number | null; source_url: string; institution_group?: string | null }
export interface Indicator { name: string; value: number | string | null; state: string; explanation: string; points?: number | null; quality?: Quality; direction_pct?: number | null }
export interface HistoryItem { date: string; code: string; group?: string; shares?: number | null; delta_shares?: number | null; estimated_flow?: number | null; nav?: number | null; quality?: Quality }
export interface Analysis { latest_shares: number | null; share_date: string | null; delta_shares: number | null; delta_pct: number | null; estimated_flow: number | null; flow_5d: number | null; flow_20d: number | null; price: number | null; quote_time: string | null; price_time?: string | null; premium_pct: number | null; quality: Quality; score: number | null; coverage: number | null; label: string; indicators: Indicator[]; intraday_indicators?: Indicator[]; quote_age_seconds?: number | null; history: HistoryItem[] }
export interface ETFAnalysis extends Analysis { code: string; name: string; group: string; enabled?: boolean }
/** 分组 coverage 为可估算样本数量，不是分析 coverage 的百分比，也不是数据质量。 */
export interface GroupSummary { group: string; flow: number | null; count?: number; coverage?: number | null; quality?: Quality }
export interface MarketRecord extends RecordMeta { trade_date: string; metric: 'turnover' | 'margin'; value: number }
export interface Dashboard { mode: 'live' | 'demo'; as_of: string; etfs: ETFAnalysis[]; groups: GroupSummary[]; market: MarketRecord[]; notice: string }
export interface SourceHealth { source: string; status: string; last_success?: string | null; error?: string | null; message?: string; count?: number; last_attempt?: string | null; checked_at?: string | null }
export interface Health { mode: 'live' | 'demo'; status: string; now: string; sources: SourceHealth[]; scheduler_enabled: boolean }
export interface ETFDetail { etf: ETF; analysis: Analysis; shares: ShareRecord[]; quotes: QuoteRecord[]; bars: BarRecord[]; navs: NavRecord[]; holders: HolderRecord[] }
export interface Alert { id: string | number; code: string; kind: string; severity: string; title: string; message: string; created_at: string; acknowledged: boolean }
export type TaskKind = 'refresh' | 'backfill' | 'holders' | 'market' | 'calendar' | 'catalogue' | 'shares';
export interface TaskRequest { kind: TaskKind; start?: string; end?: string; codes?: string[]; interval?: 'day' | '1m' | '5m'; group?: string; asset_class?: string }
export interface Task { id: string; kind: TaskKind; status: string; progress: number; message: string; created_at: string; finished_at?: string | null; start?: string; end?: string; codes?: string[]; interval?: 'day' | '1m' | '5m'; group?: string; asset_class?: string; errors?: string[] }
export interface Settings { mode: 'live' | 'demo'; scheduler_enabled: boolean; quote_interval: number; request_timeout: number; max_retries: number; max_backfill_days: number; alert_cooldown_seconds: number; shares_alert_pct: number; [key: string]: unknown }
export type SettingsUpdate = Pick<Settings, 'scheduler_enabled' | 'quote_interval' | 'alert_cooldown_seconds' | 'shares_alert_pct'>;
export interface ListResponse<T> { items: T[] }

/** 纯份额周期：自然周/月采用期末存量，不将日存量相加。 */
export type SharePeriod = 'day' | 'week' | 'month';
export type ShareFrequency = SharePeriod;
export interface SharesOverviewParams { as_of?: string; period?: SharePeriod; asset_class?: string; group?: string }
export interface ShareGroupParams { as_of?: string; period?: SharePeriod }
export interface SharesHistoryParams { start?: string; end?: string; frequency?: ShareFrequency; group?: string; code?: string }
export interface CatalogueParams { asset_class?: string; group?: string; classification_status?: Exclude<ClassificationStatus, 'unknown'>; q?: string; limit?: number; offset?: number }
export interface ExportSharesParams { as_of?: string; period?: SharePeriod; group?: string }
/** 纯份额产品指标：份额及增减单位为份，比例单位为百分比，缺失数值保留空值。 */
export interface ShareItem {
  code: string; name: string; group: string; asset_class: string;
  shares: number | null; trade_date: string | null; delta_shares: number | null; delta_pct: number | null;
  delta_5d: number | null; delta_20d: number | null; increase_streak: number | null; decrease_streak: number | null;
  quality: Quality; reason: string; source: string; classification_status: ClassificationStatus;
  baseline_date?: string | null; delta_5d_pct?: number | null; delta_20d_pct?: number | null;
  quality_5d?: Quality; quality_20d?: Quality; reason_5d?: string; reason_20d?: string; new_member?: boolean | null;
}
/** 同日分组统计：可比集合与分类分母分开，缺失计数不能伪装为零。 */
export interface ShareGroupSummary {
  group: string; asset_class: string; total_shares: number | null; delta_shares: number | null; delta_pct: number | null;
  increased: number | null; decreased: number | null; unchanged: number | null; missing_count: number | null;
  candidate_count: number | null; total_count: number | null; available_count: number | null; comparable_count: number | null;
  coverage_pct: number | null; trade_date: string | null; quality: Quality;
  unclassified_count?: number | null; new_count?: number | null; exited_count?: number | null; availability_pct?: number | null;
}
/** 覆盖元数据保留服务端扩展字段，常用统计字段解码为空值而非零。 */
export interface SharesCoverage {
  total_count?: number | null; available_count?: number | null; comparable_count?: number | null;
  missing_count?: number | null; candidate_count?: number | null; coverage_pct?: number | null;
  unclassified_count?: number | null; availability_pct?: number | null; trade_date?: string | null; baseline_date?: string | null;
  calendar_available?: boolean | null; calendar_complete?: boolean | null;
  [key: string]: unknown;
}
export interface SharesOverview {
  as_of: string; statistics_date?: string | null; requested_as_of?: string; date_selection?: string;
  period?: SharePeriod | 'unknown'; items: ShareItem[]; groups: ShareGroupSummary[];
  coverage: SharesCoverage; notice: string; mode: ApiMode;
}
export interface ShareGroupResponse { group: ShareGroupSummary; items: ShareItem[]; mode: ApiMode; notice: string }
export interface SharesHistoryItem {
  date: string; group: string; code?: string; name?: string; asset_class?: string; shares?: number | null; reason?: string; source?: string;
  total_shares: number | null; delta_shares: number | null; delta_pct: number | null;
  comparable_count: number | null; total_count: number | null; coverage_pct: number | null; quality: Quality;
  baseline_date?: string | null; trade_date?: string | null; availability_pct?: number | null;
  available_count?: number | null; candidate_count?: number | null; unclassified_count?: number | null;
  missing_count?: number | null; new_count?: number | null; exited_count?: number | null;
  increased?: number | null; decreased?: number | null; unchanged?: number | null;
}
export interface SharesHistoryResponse {
  items: SharesHistoryItem[]; mode: ApiMode; frequency: ShareFrequency | 'unknown'; notice: string;
  total?: number | null; calendar_complete?: boolean | null;
}
/** 页面兼容名称与集中契约指向同一类型，不维护重复定义。 */
export type ShareHistoryItem = SharesHistoryItem;
export type SharesHistory = SharesHistoryResponse;
/** 目录覆盖保留来源原始元数据，未知字段不推断成功或完整。 */
export interface CatalogueCoverage {
  /** 当前后端按来源名称给出数量映射；数组仅兼容早期客户端样本。 */
  sources?: Record<string, number | null> | unknown[];
  confirmed?: number | null; candidate?: number | null; unclassified?: number | null; enabled?: number | null; notice?: string;
  [key: string]: unknown;
}
export interface CatalogueResponse { items: ETF[]; total: number | null; coverage: CatalogueCoverage; mode?: ApiMode; notice?: string }
export interface ClassificationRequest {
  code: string; group: string; asset_class: string; tracking_index?: string | null; classification_status: 'confirmed'; enabled?: boolean;
}
