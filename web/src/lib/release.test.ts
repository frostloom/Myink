// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { probeRelease, requestReleaseRefresh, releaseFromHtml } from './release'
const release = (id: string, client = 'vue') => ({ schema: 1, client, id, entry: '/assets/app.js' })
const html = (id: string) => `<meta name="myink-release" content='${JSON.stringify(release(id))}'><script type="module" src="/assets/app.js"></script>`
it('requires a production identity and matching actual entry', () => {
  expect(releaseFromHtml('<script src="/assets/index-new.js"></script>')).toBeNull()
  expect(releaseFromHtml(html('vue-123'))?.id).toBe('vue-123')
  expect(releaseFromHtml(html('vue-123').replace('src="/assets/app.js"', 'src="/wrong.js"'))).toBeNull()
})
it('rejects mixed manifest and HTML and accepts matching content identity even with identical entry filename', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(release('vue-456')))).mockResolvedValueOnce(new Response(html('vue-789')))
  expect(await probeRelease(release('vue-123'), new AbortController().signal, fetcher)).toBeNull()
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify(release('vue-456')))).mockResolvedValueOnce(new Response(html('vue-456')))
  expect((await probeRelease(release('vue-123'), new AbortController().signal, fetcher))?.id).toBe('vue-456')
})
it('blocks pending writes and cancelled confirmations; confirms detailed loss warning before reload', () => {
  const reload = vi.fn(); const confirm = vi.fn((_message: string) => false)
  expect(requestReleaseRefresh(() => true, confirm, reload)).toBe(false)
  expect(confirm).not.toHaveBeenCalled()
  expect(requestReleaseRefresh(() => false, confirm, reload)).toBe(false)
  expect(reload).not.toHaveBeenCalled()
  confirm.mockReturnValue(true)
  expect(requestReleaseRefresh(() => false, confirm, reload)).toBe(true)
  expect(reload).toHaveBeenCalledOnce()
  expect(confirm.mock.calls[0]?.[0]).toMatch(/章节.*新建.*短篇.*管理员.*反馈.*主题.*导出/)
})
it('rejects malformed manifests, entry mismatch, failed requests and aborted reads', async () => {
  const current = release('vue-123')
  for (const value of [{ ...release('vue-456'), schema: 2 }, { ...release('vue-456'), entry: 'https://other.test/app.js' }, { ...release('vue-456'), id: 'unbound-name' }]) {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value)))
    expect(await probeRelease(current, new AbortController().signal, fetcher)).toBeNull()
    expect(fetcher).toHaveBeenCalledOnce()
  }
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(release('vue-456')))).mockResolvedValueOnce(new Response(html('vue-456').replace('src="/assets/app.js"', 'src="/assets/other.js"')))
  expect(await probeRelease(current, new AbortController().signal, fetcher)).toBeNull()
  const controller = new AbortController(); controller.abort()
  expect(await probeRelease(current, controller.signal, vi.fn().mockResolvedValue(new Response(JSON.stringify(release('vue-456')))))).toBeNull()
  expect(await probeRelease(current, new AbortController().signal, vi.fn().mockResolvedValue(new Response('', { status: 503 })))).toBeNull()
})
it('rechecks write lock after the confirmation callback', () => {
  let pending = false
  const reload = vi.fn()
  expect(requestReleaseRefresh(() => pending, () => { pending = true; return true }, reload)).toBe(false)
  expect(reload).not.toHaveBeenCalled()
})
