import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 阶段 4 前端工作台：开发期经 /api 代理到本地边缘（Caddy，:80）——同源，无 CORS。
// 不指 127.0.0.1:8100：Python 容器不对宿主发布端口（仅容器网络内 8100），且 SSE 仍在
// 网关那边，只有 Caddy 这一个目标能同时覆盖业务 API 与 SSE。
// SITE_ADDRESS 换成域名/HTTPS 时，这里也要跟着改成 https://<域名>。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:80',
        changeOrigin: true,
      },
    },
  },
})
