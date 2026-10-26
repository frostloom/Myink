// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { authenticatedGet, authenticatedSend } from './api'
function protectedUnload() {
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  return event.defaultPrevented
}
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })
it('protects an in-flight mutation until response parsing completes', async () => {
  let finish!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => new Promise(resolve => { finish = resolve }) }))
  const writing = authenticatedSend('PUT', '/environment', '', {})
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  const protectedWhileSaving = protectedUnload()
  finish({ ok: true }); await writing
  expect(protectedWhileSaving).toBe(true)
  expect(protectedUnload()).toBe(false)
})
it('keeps concurrent write protection after one fails, then releases the last lock', async () => {
  let fail!: (reason: Error) => void, finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => new Promise((_, reject) => { fail = reject }))
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve })))
  const first = authenticatedSend('POST', '/feedback', '', new FormData()).catch(error => error)
  const second = authenticatedSend('PATCH', '/admin/configuration', '', {})
  const duringBoth = protectedUnload()
  fail(new Error('offline')); await first
  const duringSecond = protectedUnload()
  finish(new Response('{}')); await second
  expect(duringBoth).toBe(true); expect(duringSecond).toBe(true)
  expect(protectedUnload()).toBe(false)
})
it('does not block leaving for read requests', async () => {
  let finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finish = resolve })))
  const reading = authenticatedGet('/environment', '')
  const blocked = protectedUnload()
  finish(new Response('{}')); await reading
  expect(blocked).toBe(false)
})
it('releases write protection after an aborted request', async () => {
  const controller = new AbortController()
  vi.stubGlobal('fetch', vi.fn((_url, options: RequestInit) => new Promise((_, reject) => {
    options.signal?.addEventListener('abort', () => reject(new Error('aborted')))
  })))
  const writing = authenticatedSend('DELETE', '/style-library/a', '', undefined, controller.signal).catch(error => error)
  const blocked = protectedUnload()
  controller.abort(); await writing
  expect(blocked).toBe(true); expect(protectedUnload()).toBe(false)
})
