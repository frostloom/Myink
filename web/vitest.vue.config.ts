import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    include: ['vue/src/**/*.test.ts'],
    environment: 'jsdom',
    // Match a small CI runner and avoid starving jsdom timers on busy hosts.
    maxWorkers: 2,
    css: true,
    restoreMocks: true,
  },
})
