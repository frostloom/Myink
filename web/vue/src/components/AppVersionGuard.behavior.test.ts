import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { beginWrite } from '../../../src/lib/pendingWrites'
import AppVersionGuard from './AppVersionGuard.vue'
const identity = (id: string) => ({ schema: 1, client: 'vue', id, entry: '/assets/app.js' })
const html = (id: string) => `<meta name="myink-release" content='${JSON.stringify(identity(id))}'><script type="module" src="/assets/app.js"></script>`
afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.head.innerHTML = ''; vi.restoreAllMocks() })
it('offers only an explicit confirmed update and reacts to pending writes', async () => {
  document.head.innerHTML = html('vue-123')
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(identity('vue-456')))).mockResolvedValueOnce(new Response(html('vue-456'))))
  render(AppVersionGuard)
  const button = await screen.findByRole('button', { name: '刷新到新版本' }) as HTMLButtonElement
  expect(confirm).not.toHaveBeenCalled()
  const finish = beginWrite()
  await waitFor(() => expect(button.disabled).toBe(true))
  fireEvent.click(button)
  expect(confirm).not.toHaveBeenCalled()
  finish()
  await waitFor(() => expect(button.disabled).toBe(false))
  await fireEvent.click(button)
  expect(confirm).toHaveBeenCalledOnce()
  expect(screen.getByRole('status')).toBeTruthy()
})
it('does not probe development pages and aborts in-flight probes on unmount', () => {
  const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}))
  vi.stubGlobal('fetch', fetcher)
  const dev = render(AppVersionGuard)
  expect(fetcher).not.toHaveBeenCalled()
  dev.unmount()
  document.head.innerHTML = html('vue-123')
  const mounted = render(AppVersionGuard)
  expect(fetcher).toHaveBeenCalledOnce()
  const signal = fetcher.mock.calls[0]?.[1].signal as AbortSignal
  mounted.unmount()
  expect(signal.aborted).toBe(true)
})
