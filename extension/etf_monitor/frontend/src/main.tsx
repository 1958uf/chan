import { Component, type ErrorInfo, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

/** 功能：拦截渲染异常，不让空白页面掩盖故障；输入：应用节点；输出：应用或明确错误页。 */
class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  /** 功能：记录渲染失败状态；输入：异常；输出：失败状态。 */
  static getDerivedStateFromError(): { failed: boolean } { return { failed: true }; }
  /** 功能：输出诊断信息；输入：异常与组件信息；输出：控制台日志。 */
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('ETF 前端渲染失败', error, info); }
  /** 功能：渲染错误提示或子节点；输入：组件状态；输出：页面节点。 */
  render() { return this.state.failed ? <div className="fatal-error"><h1>页面渲染失败</h1><p>未能展示数据，不代表系统正常。请重新加载并检查后端健康。</p><button onClick={() => window.location.reload()}>重新加载</button></div> : this.props.children; }
}

createRoot(document.getElementById('root')!).render(<ErrorBoundary><App /></ErrorBoundary>);
