import { useEffect, useState } from 'react';
import { api } from './api/client';
import { Badge, ResourceStatus, ToastProvider, useResource } from './ui';
import { LegacyDashboardPage, ETFPage } from './pages/Dashboard';
import { DashboardPage, GroupPage } from './pages/Shares';
import { CataloguePage } from './pages/Catalogue';
import { DetailPage } from './pages/Detail';
import { HistoryPage, LegacyHistoryPage, HoldersPage } from './pages/History';
import { AlertsPage, HealthPage, TasksPage } from './pages/Operations';
import { SettingsPage, WatchlistPage } from './pages/Management';

const pages = [
  ['dashboard', '份额总览', '01'], ['history', '份额历史', '02'], ['catalogue', '发现目录', '03'], ['watchlist', '精选观察池', '04'],
  ['etfs', 'ETF 检索', '05'], ['intraday', '盘中总览（辅助）', '06'], ['legacy-history', '历史流量（辅助）', '07'], ['holders', '持有人报告', '08'],
  ['alerts', '告警中心', '09'], ['tasks', '采集任务', '10'], ['health', '数据源健康', '11'], ['settings', '运行配置', '12'],
] as const;
type Page = typeof pages[number][0] | 'detail' | 'group';
/** 功能：读取受限 hash 路由；输入：当前地址；输出：合法页面及代码或分组。 */
function readRoute(): { page: Page; code: string } {
  const route = window.location.hash.replace(/^#\/?/, '').split('/');
  if (route[0] === 'etfs' && /^\d{6}$/.test(route[1] || '')) return { page: 'detail', code: route[1] };
  if (route[0] === 'groups' && route[1]) {
    try { const group = decodeURIComponent(route[1]); if (group.length > 0 && group.length <= 40) return { page: 'group', code: group }; }
    catch { /* 损坏的地址不进入分组接口，回退首页。 */ }
  }
  return { page: pages.some(([page]) => page === route[0]) ? route[0] as Page : 'dashboard', code: '' };
}
/** 功能：渲染中文导航、全页模式横幅与真实数据页；输入：无；输出：应用壳。 */
function AppContent() {
  const [route, setRoute] = useState(readRoute);
  const health = useResource(() => api.health(), [], 15000);
  useEffect(() => {
    const change = () => { setRoute(readRoute()); window.scrollTo({ top: 0 }); };
    window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change);
  }, []);
  /** 功能：跳转到合法标的详情；输入：六位代码；输出：更新 hash。 */
  const onDetail = (code: string) => { window.location.hash = `/etfs/${code}`; };
  const mode = health.error ? null : health.data?.mode;
  let content;
  switch (route.page) {
    case 'etfs': content = <ETFPage onDetail={onDetail} />; break;
    case 'detail': content = <DetailPage code={route.code} onBack={() => { window.location.hash = '/etfs'; }} />; break;
    case 'history': content = <HistoryPage />; break;
    case 'legacy-history': content = <LegacyHistoryPage />; break;
    case 'intraday': content = <LegacyDashboardPage onDetail={onDetail} />; break;
    case 'catalogue': content = <CataloguePage />; break;
    case 'group': content = <GroupPage group={route.code} onDetail={onDetail} />; break;
    case 'holders': content = <HoldersPage />; break;
    case 'alerts': content = <AlertsPage />; break;
    case 'tasks': content = <TasksPage />; break;
    case 'health': content = <HealthPage />; break;
    case 'watchlist': content = <WatchlistPage />; break;
    case 'settings': content = <SettingsPage />; break;
    default: content = <DashboardPage onDetail={onDetail} />;
  }
  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="#/dashboard"><span className="brand-mark">E</span><div>ETF 观察站<small>份额与证据监控</small></div></a><div className="sidebar-label">独立工作空间</div><nav aria-label="主导航">{pages.map(([page, label, index]) => <a key={page} href={`#/${page}`} className={route.page === page || (page === 'etfs' && route.page === 'detail') ? 'active' : ''} aria-current={route.page === page ? 'page' : undefined}><span>{index}</span>{label}</a>)}</nav><div className="sidebar-bottom"><strong>研究观察工具</strong><p>份额变化不是资金流<br />不构成投资建议<br />不识别机构实时交易</p></div></aside><div className="main-shell"><header className="topbar"><span>中国市场 / Asia·Shanghai</span><div><span className="connection-dot" /><span>{mode === 'demo' ? '演示数据连接' : mode === 'live' ? '真实模式连接' : '连接待确认'}</span><Badge value={mode === 'demo' ? 'demo' : health.error ? 'error' : health.data?.sources.length === 0 ? 'missing' : health.data?.status} /></div></header><main id="main-content"><div className={`mode-banner ${mode === 'live' ? 'live' : ''}`} role="status" data-testid="mode-banner"><strong>{mode === 'demo' ? '演示模式 · 固定 seed 样例，不代表真实市场' : mode === 'live' ? '真实数据模式 · 缺失/陈旧以数据质量标记为准' : '模式未知 · 无法验证后端状态，不认定数据正常'}</strong><span>份额单位：亿份 · 同日存量与可比变化分开 · 行情及评分仅作辅助</span></div><ResourceStatus resource={health} /><div key={`${route.page}-${route.code}`}>{content}</div><footer>ETF 观察站 · 独立系统 · 行情与份额时间分离 · 数据来源与公告日期请核验</footer></main></div></div>;
}
/** 功能：提供统一通知上下文；输入：无；输出：可运行应用。 */
export default function App() { return <ToastProvider><AppContent /></ToastProvider>; }
