import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// 功能：在组件测试中清理页面和 mock；输入：每次测试状态；输出：隔离的下一次测试。
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ''; });
// 图表在组件测试中用独立 mock，真实 canvas 由 Playwright 验证。
Object.defineProperty(window, 'scrollTo', { value: vi.fn(), writable: true });
