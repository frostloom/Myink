import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { resolveConfig } from 'vite'
const web = fileURLToPath(new URL('..', import.meta.url))

test('normal Vite build selects native Vue and its isolated output', async () => {
  const config = await resolveConfig({ configFile: resolve(web, 'vite.config.ts') }, 'build')
  assert.equal(config.root, resolve(web, 'vue'), 'default Vite still selects the React HTML root')
  assert.equal(resolve(config.root, config.build.outDir), resolve(web, 'dist-vue'))
  assert.ok(config.plugins.some(plugin => plugin.name === 'vite:vue'))
  assert.ok(config.plugins.some(plugin => plugin.name === 'vue-production-boundary'))
})

test('production boundary rejects an accidentally reintroduced alternate runtime', async () => {
  const config = await resolveConfig({ configFile: resolve(web, 'vite.config.ts') }, 'build')
  const boundary = config.plugins.find(plugin => plugin.name === 'vue-production-boundary')
  const context = { error(message) { throw new Error(message) } }
  assert.throws(() => boundary.generateBundle.call(context, {}, {
    'bad.js': { type: 'chunk', modules: { '/node_modules/react/index.js': {} } },
  }), /production bundle contains/)
})
