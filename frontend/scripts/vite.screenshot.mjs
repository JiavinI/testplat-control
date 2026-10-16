/**
 * 截图专用 Vite 配置。
 * 仓库 vite.config.ts 使用 changeOrigin，会把 Host 改成后端地址，
 * 平台登录的 Origin 校验因此返回 403。这里保持浏览器的 Host。
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const target = process.env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  root,
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(root, 'src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target,
        changeOrigin: false,
        rewrite: (requestPath) => requestPath.replace(/^\/api/, ''),
      },
    },
  },
})
