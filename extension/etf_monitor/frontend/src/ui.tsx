import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { Quality } from './api/types';

export interface Resource<T> { data: T | null; loading: boolean; error: string | null; reload: () => Promise<void> }
/** 功能：加载真实 API，标明失败和陈旧缓存；输入：加载函数与依赖；输出：资源状态。 */
export function useResource<T>(loader: () => Promise<T>, dependencies: readonly unknown[] = [], pollMs = 0): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loaderRef = useRef(loader); loaderRef.current = loader;
  const alive = useRef(false);
  const sequence = useRef(0);
  const toast = useToast();
  const previousError = useRef<string | null>(null);
  const reload = useCallback(async () => {
    const current = ++sequence.current;
    setLoading(true);
    try {
      const result = await loaderRef.current();
      if (alive.current && current === sequence.current) { setData(result); setError(null); previousError.current = null; }
    } catch (failure) {
      if (alive.current && current === sequence.current) {
        const message = failure instanceof Error ? failure.message : '接口请求失败';
        setError(message);
        if (previousError.current !== message) toast(message, 'error');
        previousError.current = message;
      }
    } finally { if (alive.current && current === sequence.current) setLoading(false); }
  }, [toast]);
  useEffect(() => {
    alive.current = true; setData(null); previousError.current = null;
    void reload();
    const timer = pollMs ? window.setInterval(() => { if (document.visibilityState === 'visible') void reload(); }, pollMs) : undefined;
    return () => { alive.current = false; ++sequence.current; window.clearInterval(timer); };
    // 查询依赖由调用页显式声明，loaderRef 避免每次渲染重复轮询。
  }, [...dependencies, reload, pollMs]);
  return { data, loading, error, reload };
}

interface ToastItem { id: number; message: string; kind: 'error' | 'success' }
type Notify = (message: string, kind?: 'error' | 'success') => void;
const ToastContext = createContext<Notify>(() => undefined);
/** 功能：获取统一提示入口；输入：无；输出：通知函数。 */
export function useToast(): Notify { return useContext(ToastContext); }
/** 功能：管理可关闭提示；输入：子节点；输出：带提示区域的组件。 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const timers = useRef<number[]>([]);
  const notify = useCallback<Notify>((message, kind = 'success') => {
    const id = ++nextId.current;
    setItems(previous => [...previous.slice(-3), { id, message, kind }]);
    timers.current.push(window.setTimeout(() => setItems(previous => previous.filter(item => item.id !== id)), 7000));
  }, []);
  useEffect(() => () => timers.current.forEach(window.clearTimeout), []);
  return <ToastContext.Provider value={notify}>{children}<div className="toast-stack" aria-live="polite">{items.map(item => <div key={item.id} className={`toast ${item.kind}`} role={item.kind === 'error' ? 'alert' : 'status'}><span>{item.message}</span><button aria-label="关闭提示" onClick={() => setItems(previous => previous.filter(entry => entry.id !== item.id))}>×</button></div>)}</div></ToastContext.Provider>;
}
/** 功能：包装用户变更并抑制重复提交；输入：无；输出：执行函数和忙状态。 */
export function useMutation() {
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const notify = useToast();
  /** 功能：执行变更并如实通知；输入：异步操作和成功文案；输出：是否成功。 */
  const run = async (action: () => Promise<unknown>, message: string): Promise<boolean> => {
    if (locked.current) return false;
    locked.current = true; setBusy(true);
    try { await action(); notify(message); return true; }
    catch (error) { notify(error instanceof Error ? error.message : '操作失败', 'error'); return false; }
    finally { locked.current = false; setBusy(false); }
  };
  return { busy, run };
}
/** 功能：格式化数值但不掩盖缺失；输入：数字、小数位；输出：显示文本。 */
export function number(value: number | null | undefined, digits = 2): string { return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits }); }
/** 功能：用亿单位展示金额或份额；输入：原始值；输出：数值文本。 */
export function billion(value: number | null | undefined): string { return value == null ? '—' : number(value / 1e8); }
/** 功能：格式化带时区时间；输入：时间文本；输出：中国时区时间或未知。 */
export function time(value: string | null | undefined): string {
  if (!value) return '未知';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' });
}
/** 功能：质量状态保守着色，未知不判正常；输入：质量/状态；输出：徽标。 */
export function Badge({ value }: { value: Quality | string | null | undefined }) {
  const labels: Record<string, string> = { valid: '有效', demo: '演示', partial: '部分缺失', stale: '陈旧', suspect: '可疑', missing: '缺失', error: '失败', unknown: '未知', ok: '正常', healthy: '正常', degraded: '降级', empty: '无数据', failed: '失败', pending: '待执行', queued: '排队', running: '执行中', completed: '已完成', success: '已完成', succeeded: '已完成', cancelled: '已取消', cancelling: '取消中', disabled: '已停用' };
  const safe = value === 'valid' ? 'good' : ['error', 'failed'].includes(value || '') ? 'bad' : 'warn';
  return <span className={`badge ${safe}`}>{labels[value || 'unknown'] || value || '未知'}</span>;
}
/** 功能：展示读取状态，失败缓存显式陈旧；输入：资源；输出：状态区域。 */
export function ResourceStatus({ resource }: { resource: Resource<unknown> }) {
  if (resource.error) return <div className="error-panel" role="alert"><strong>读取失败{resource.data ? ' · 当前显示上次缓存，不能视为最新' : ''}</strong><span>{resource.error}</span><button onClick={() => void resource.reload()} disabled={resource.loading}>重试</button></div>;
  if (resource.loading && !resource.data) return <div className="empty" role="status">正在读取后端数据…</div>;
  return null;
}
/** 功能：说明真实空状态；输入：空状态文本；输出：占位提示。 */
export function Empty({ children = '暂无数据。请先创建采集任务，并在健康页检查数据源；不会自动填充演示数据。' }: { children?: ReactNode }) { return <div className="empty">{children}</div>; }
/** 功能：下载已有 Blob；输入：文件和名称；输出：浏览器下载。 */
export function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
