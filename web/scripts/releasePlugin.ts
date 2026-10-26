import { createHash } from 'node:crypto'
import type { Plugin } from 'vite'
export function buildRelease(client: 'vue' | 'react', assets: Record<string, string | Uint8Array>, entry: string) {
  const hash = createHash('sha256').update(client).update('\0').update(entry)
  for (const name of Object.keys(assets).sort()) {
    const bytes = assets[name]!
    hash.update('\0').update(name).update('\0').update(String(Buffer.byteLength(bytes))).update('\0').update(bytes)
  }
  return { schema: 1, client, id: `${client}-${hash.digest('hex')}`, entry }
}
export function releasePlugin(client: 'vue' | 'react'): Plugin {
  return {
    name: 'myink-release-identity', apply: 'build', enforce: 'post',
    generateBundle: {
      order: 'post',
      handler(_options, bundle) {
        const index = bundle['index.html']
        if (!index || index.type !== 'asset' || typeof index.source !== 'string') this.error('Release identity requires index.html')
        const entry = index.source.match(/<script\b[^>]*\btype="module"[^>]*\bsrc="([^"]+)"/)?.[1]
        if (!entry || !bundle[entry.replace(/^\//, '')]) this.error('Release identity requires a built module entry')
        if (!/^\/assets\/index-[\w-]+\.js$/.test(entry)) this.error('Legacy clients require assets/index-[hash].js entry naming')
        const assets: Record<string, string | Uint8Array> = {}
        for (const [name, output] of Object.entries(bundle)) if (name !== 'index.html' && name !== 'release.json') assets[name] = output.type === 'chunk' ? output.code : output.source
        // Bind HTML as well; the injected identity itself is deliberately excluded.
        assets['index.html'] = index.source
        const release = buildRelease(client, assets, entry)
        index.source = index.source.replace('</head>', `<meta name="myink-release" content='${JSON.stringify(release)}'>\n</head>`)
        this.emitFile({ type: 'asset', fileName: 'release.json', source: JSON.stringify(release) })
      },
    },
  }
}
