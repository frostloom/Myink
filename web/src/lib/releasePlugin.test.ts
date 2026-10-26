import { expect, it } from 'vitest'
import { buildRelease } from '../../scripts/releasePlugin'
it('binds identity to all app bytes and client while ignoring object insertion order', () => {
  const assets = { 'assets/app.js': 'one', 'assets/app.css': 'css' }
  expect(buildRelease('vue', assets, '/assets/app.js')).toEqual(buildRelease('vue', { 'assets/app.css': 'css', 'assets/app.js': 'one' }, '/assets/app.js'))
  expect(buildRelease('vue', assets, '/assets/app.js').id).not.toBe(buildRelease('react', assets, '/assets/app.js').id)
  expect(buildRelease('vue', assets, '/assets/app.js').id).not.toBe(buildRelease('vue', { ...assets, 'assets/app.css': 'changed' }, '/assets/app.js').id)
})
it('emits a matching manifest and HTML with deterministic identity through a real Vite build', async () => {
  const { mkdtemp, writeFile, rm } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const { build } = await import('vite')
  const { releasePlugin } = await import('../../scripts/releasePlugin')
  const root = await mkdtemp(join(tmpdir(), 'myink-release-'))
  try {
    await writeFile(join(root, 'index.html'), '<html><head></head><body><script type="module" src="/main.js"></script></body></html>')
    await writeFile(join(root, 'main.js'), 'console.log("release fixture")')
    const run = async (client: 'vue' | 'react') => {
      const result = await build({ configFile: false, root, logLevel: 'silent', plugins: [releasePlugin(client)], build: { write: false } })
      if (Array.isArray(result) || !('output' in result)) throw new Error('Expected output bundle')
      const assets = result.output.filter(output => output.type === 'asset')
      const html = String(assets.find(asset => asset.fileName === 'index.html')?.source)
      const manifest = JSON.parse(String(assets.find(asset => asset.fileName === 'release.json')?.source))
      expect(html).toContain(`content='${JSON.stringify(manifest)}'`)
      expect(html).toContain(`src="${manifest.entry}"`)
      expect(result.output.some(output => `/${output.fileName}` === manifest.entry)).toBe(true)
      return manifest.id
    }
    const first = await run('vue')
    expect(await run('vue')).toBe(first)
    expect(await run('react')).not.toBe(first)
    await writeFile(join(root, 'main.js'), 'console.log("changed app")')
    expect(await run('vue')).not.toBe(first)
  } finally { await rm(root, { recursive: true, force: true }) }
})
it('rejects an entry filename that cannot be recognized by still-active legacy clients', async () => {
  const { mkdtemp, writeFile, rm } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const { build } = await import('vite')
  const { releasePlugin } = await import('../../scripts/releasePlugin')
  const root = await mkdtemp(join(tmpdir(), 'myink-release-legacy-'))
  try {
    await writeFile(join(root, 'index.html'), '<html><head></head><body><script type="module" src="/main.js"></script></body></html>')
    await writeFile(join(root, 'main.js'), 'console.log("legacy fixture")')
    await expect(build({ configFile: false, root, logLevel: 'silent', plugins: [releasePlugin('vue')], build: { write: false, rolldownOptions: { output: { entryFileNames: 'assets/app-[hash].js' } } } })).rejects.toThrow(/legacy.*index-/i)
  } finally { await rm(root, { recursive: true, force: true }) }
})
