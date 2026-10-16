/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 开发代理目标可被 VITE_DEV_PROXY_TARGET 覆盖，默认本机 FastAPI
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      proxy: {
        // 前缀 /api 转发到后端并剥掉前缀。浏览器只跟 Vite 同源，不直连后端，因此没有 CORS。
        // changeOrigin 必须保持 false：后端用 Host 做 Origin 校验，改写 Host 会让登录和注册返回 403。
        // 精确匹配 API 前缀，避免把 /apis 等前端页面也转发给后端。
        '^/api(?:/|$)': {
          target: proxyTarget,
          changeOrigin: false,
          rewrite: (p) => p.replace(/^\/api/, ''),
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      // antd + userEvent 在高并行下易超时，限制 worker 并放宽单测时限
      testTimeout: 20_000,
      maxWorkers: 2,
    },
  }
})
