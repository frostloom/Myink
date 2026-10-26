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

test('explicit React rollback keeps its own HTML root and output', async () => {
  const config = await resolveConfig({ root: web, configFile: resolve(web, 'vite.react.config.ts') }, 'build')
  assert.equal(config.root, resolve(web))
  assert.equal(resolve(config.root, config.build.outDir), resolve(web, 'dist'))
  assert.ok(config.plugins.some(plugin => plugin.name.startsWith('vite:react')))
  assert.equal(config.plugins.some(plugin => plugin.name === 'vue-production-boundary'), false)
})
