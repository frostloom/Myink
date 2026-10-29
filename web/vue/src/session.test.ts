import { afterEach, expect, it, vi } from 'vitest'
import { createSessionScope } from './session'
import { SESSION_STORAGE_KEY, setSession } from '../../src/lib/token'

const scopes: ReturnType<typeof createSessionScope>[] = []
const stored = (userId = 'a', token = 'token-a') => ({ userId, token, username: userId, tier: 'pro', role: 'admin' as const, roleVerified: true, expiresAt: Date.now() + 3600000 })
const remote = (userId = 'a') => ({ user_id: userId, username: `verified-${userId}`, tier: 'pro', role: 'user', token: `renewed-${userId}`, expires_in: 3600 })
function scope() { const s = createSessionScope(); scopes.push(s); return s }
function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }) }
afterEach(() => { scopes.splice(0).forEach(s => s.dispose()); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('does not request protected data or trust an absent session', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  const s = scope(); await s.start()
  expect(s.status.value).toBe('anonymous'); expect(s.session.value).toBeNull(); expect(fetcher).not.toHaveBeenCalled()
})

it('waits for the server and never trusts a cached admin role', async () => {
  setSession(stored()); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { finish = r })))
  const s = scope(); const pending = s.start()
  expect(s.status.value).toBe('checking'); expect(s.session.value?.roleVerified).not.toBe(true)
  finish(response(remote())); await pending
  expect(s.status.value).toBe('authenticated'); expect(s.session.value?.role).toBe('user'); expect(s.session.value?.username).toBe('verified-a')
})

it('retains a session on service outage and can retry validation', async () => {
  setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(response(remote())))
  const s = scope(); await s.start()
  expect(s.status.value).toBe('unavailable'); expect(localStorage.getItem(SESSION_STORAGE_KEY)).not.toBeNull()
  await s.revalidate(); expect(s.status.value).toBe('authenticated')
})

it('clears a genuinely rejected session', async () => {
  setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: 'unauthorized' }, 401)))
  const s = scope(); await s.start()
  expect(s.status.value).toBe('anonymous'); expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
})

it('does not let an old validation overwrite an account switched in storage', async () => {
  setSession(stored()); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise<Response>(r => { finish = r })).mockResolvedValue(response(remote('b'))))
  const s = scope(); const first = s.start()
  setSession(stored('b', 'token-b')); await s.revalidate()
  finish(response(remote('a'))); await first
  expect(s.session.value?.userId).toBe('b'); expect(s.session.value?.username).toBe('verified-b')
})

it('reacts to cross-tab logout and stops listening after disposal', async () => {
  setSession(stored()); const fetcher = vi.fn().mockResolvedValue(response(remote())); vi.stubGlobal('fetch', fetcher)
  const s = scope(); await s.start(); localStorage.clear()
  window.dispatchEvent(new StorageEvent('storage', { key: SESSION_STORAGE_KEY }))
  expect(s.status.value).toBe('anonymous')
  s.dispose(); setSession(stored('b', 'token-b')); window.dispatchEvent(new StorageEvent('storage', { key: SESSION_STORAGE_KEY }))
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('leaves checking if a token expires while its validation is in flight', async () => {
  let now = Date.now(); vi.spyOn(Date, 'now').mockImplementation(() => now)
  setSession(stored()); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { finish = r })))
  const s = scope(); const pending = s.start(); now += 3600001
  finish(response(remote())); await pending
  expect(s.status.value).toBe('anonymous'); expect(s.session.value).toBeNull()
})

it('does not clear a new stored account when an old request reports unauthorized', async () => {
  setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockImplementation(async (_path: string, init: RequestInit) => {
    const user = (init.headers as Record<string, string>).Authorization === 'Bearer token-b' ? 'b' : 'a'
    return response(remote(user))
  }))
  const s = scope(); await s.start(); setSession(stored('b', 'token-b'))
  window.dispatchEvent(new CustomEvent('myink:unauthorized', { detail: { token: 'token-a' } }))
  await vi.waitFor(() => expect(s.session.value?.userId).toBe('b'))
  expect(localStorage.getItem(SESSION_STORAGE_KEY)).toContain('token-b')
})
