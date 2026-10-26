import { releasePlugin } from './scripts/releasePlugin.ts'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const at = (path: string) => fileURLToPath(new URL(path, import.meta.url))

export default defineConfig({
  root: at('./vue'),
  publicDir: at('./public'),
  plugins: [vue(), releasePlugin('vue'), {
    name: 'vue-production-boundary',
    generateBundle(_options, bundle) {
      for (const output of Object.values(bundle)) {
        if (output.type !== 'chunk') continue
        for (const moduleId of Object.keys(output.modules)) {
          if (/[/\\]node_modules[/\\](?:react|react-dom|react-router|react-router-dom)[/\\]/.test(moduleId) || /[/\\]src[/\\].*\.tsx(?:\?|$)/.test(moduleId)) {
            this.error(`Vue production bundle contains React source: ${moduleId}`)
          }
        }
      }
    },
  }],
  build: {
    rolldownOptions: { output: { entryFileNames: 'assets/index-[hash].js' } },
    outDir: at('./dist-vue'),
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    strictPort: true,
    fs: { allow: [at('.')] },
    // 与React一致经Caddy访问API/SSE；端口隔离不代表后端数据隔离。
    proxy: { '/api': { target: 'http://localhost:80', changeOrigin: true } },
  },
})
