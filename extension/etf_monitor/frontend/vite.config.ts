import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 功能：声明构建、测试和本地 API 代理；输入：环境变量；输出：Vite 配置。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173, strictPort: true,
    proxy: { '/api': { target: process.env.ETF_API_TARGET || 'http://127.0.0.1:8765', changeOrigin: false } },
  },
  build: { chunkSizeWarningLimit: 1800 },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], include: ['tests/**/*.test.{ts,tsx}'], restoreMocks: true },
});
