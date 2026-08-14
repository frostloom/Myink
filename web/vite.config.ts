import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 阶段 4 前端工作台：开发期经 /api 代理到 Go 网关（:8080）——网关无 CORS，
// 同源代理绕过浏览器拦截（生产静态托管/网关 CORS 归阶段 5）。SSE 同走此代理。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
