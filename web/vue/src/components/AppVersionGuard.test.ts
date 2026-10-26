import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/vue'
import AppVersionGuard from './AppVersionGuard.vue'
afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.querySelector('#version-test-script')?.remove(); document.querySelector('meta[name="myink-release"]')?.remove() })
it('offers an explicit update without automatically discarding the current editor', async () => {
  const script = document.createElement('script'); script.id = 'version-test-script'; script.type = 'module'; script.src = '/assets/index-old.js'; document.head.append(script)
  const meta = document.createElement('meta'); meta.name = 'myink-release'; meta.content = JSON.stringify({ schema: 1, client: 'vue', id: 'vue-123', entry: '/assets/index-old.js' }); document.head.append(meta)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ schema: 1, client: 'vue', id: 'vue-456', entry: '/assets/index-new.js' }))).mockResolvedValueOnce(new Response(`<meta name="myink-release" content='${JSON.stringify({ schema: 1, client: 'vue', id: 'vue-456', entry: '/assets/index-new.js' })}'><script type="module" src="/assets/index-new.js"></script>`)))
  render(AppVersionGuard)
  expect(await screen.findByRole('button', { name: '刷新到新版本' })).toBeTruthy()
  expect(screen.getByRole('status').textContent).toContain('保存')
})
it('ignores failed version probes', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
  render(AppVersionGuard)
  await Promise.resolve()
  expect(screen.queryByRole('status')).toBeNull()
})
