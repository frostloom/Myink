import { afterEach, expect, it, vi } from 'vitest'
import { createSessionScope } from './session'
import { authenticatedGet } from '../../src/lib/api'
import { getSession, setSession, SESSION_STORAGE_KEY } from '../../src/lib/token'
const scopes: ReturnType<typeof createSessionScope>[] = []
const auth = (id = 'a', token = `token-${id}`) => ({ user_id: id, username: id, tier: 'pro', role: 'user', token, expires_in: 3600 })
const stored = (id = 'a', token = `token-${id}`, expiresAt = Date.now() + 3600000) => ({ userId: id, username: id, tier: 'pro', role: 'user' as const, roleVerified: true, token, expiresAt })
const response = (body: unknown) => new Response(JSON.stringify(body))
async function scope() { const s = createSessionScope(); scopes.push(s); await s.start(); return s }
afterEach(() => { scopes.splice(0).forEach(s => s.dispose()); localStorage.clear(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('stores canonical password login and returns authenticated', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(auth())))
  const s = await scope(); expect(await s.login('A', 'short')).toEqual({ status: 'authenticated' }); expect(s.session.value?.roleVerified).toBe(true); expect(getSession()?.token).toBe('token-a')
})
it('keeps MFA challenge in memory and exchanges it', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ mfa_required: true, mfa_token: 'ticket' })).mockResolvedValueOnce(response(auth())))
  const s = await scope(); expect(await s.login('a', 'short')).toEqual({ status: 'mfa', mfaToken: 'ticket' }); expect(localStorage.length).toBe(0); expect(await s.completeMfa('ticket', '123456')).toBe(true)
})
it('forwards registration invitation without persisting it', async () => {
  const f = vi.fn().mockResolvedValue(response(auth())); vi.stubGlobal('fetch', f); const s = await scope(); await s.register('a', 'Password1', 'invitation')
  expect(JSON.parse(f.mock.calls[0]![1].body)).toEqual({ username: 'a', password: 'Password1', invitation_code: 'invitation' }); expect(localStorage.getItem(SESSION_STORAGE_KEY)).not.toContain('invitation')
})
it.each(['login', 'register', 'completeMfa'] as const)('rejects unseen storage switch during %s', async action => {
  let finish!: (r: Response) => void; vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise<Response>(r => { finish = r })).mockResolvedValue(response(auth('b'))))
  const s = await scope(); const p = action === 'login' ? s.login('a', 'p') : action === 'register' ? s.register('a', 'p', 'i') : s.completeMfa('t', '123456'); setSession(stored('b')); finish(response(auth()))
  expect(await p).toBe(action === 'completeMfa' ? false : null); expect(s.session.value?.userId).toBe('b')
})
it('renews without aborting business requests and cancels historical tokens on account switch', async () => {
  vi.useFakeTimers(); setSession(stored('a', 'token-a', Date.now() + 300000)); let signal!: AbortSignal
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => { if (url.endsWith('/business')) { signal = init.signal!; return new Promise<Response>(() => {}) }; return response(auth('a', 'rotated')) }))
  const s = await scope(); void authenticatedGet('/business', 'token-a'); await vi.advanceTimersByTimeAsync(60000)
  expect(s.status.value).toBe('authenticated'); expect(s.session.value?.token).toBe('rotated'); expect(signal.aborted).toBe(false)
  setSession(stored('b')); window.dispatchEvent(new StorageEvent('storage', { key: SESSION_STORAGE_KEY })); expect(signal.aborted).toBe(true)
})
it('retains failed renewals until expiry and retries each minute', async () => {
  vi.useFakeTimers(); setSession(stored('a', 'token-a', Date.now() + 180000)); const f = vi.fn().mockResolvedValueOnce(response(auth())).mockRejectedValue(new TypeError('offline')); vi.stubGlobal('fetch', f)
  const s = await scope(); await vi.advanceTimersByTimeAsync(60000); expect(s.status.value).toBe('authenticated'); await vi.advanceTimersByTimeAsync(60000); expect(f).toHaveBeenCalledTimes(3); await vi.advanceTimersByTimeAsync(60000); expect(s.status.value).toBe('anonymous')
})
it('checks visibility, accepts identity-only old backend and stops on dispose', async () => {
  setSession(stored('a', 'token-a', Date.now() + 240000)); const f = vi.fn().mockImplementation(async () => response({ user_id: 'a', username: 'a', tier: 'pro', role: 'user' })); vi.stubGlobal('fetch', f)
  const s = await scope(); Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); document.dispatchEvent(new Event('visibilitychange')); await vi.waitFor(() => expect(f).toHaveBeenCalledTimes(2)); expect(s.session.value?.token).toBe('token-a'); s.dispose(); document.dispatchEvent(new Event('visibilitychange')); expect(f).toHaveBeenCalledTimes(2)
})
it('does not grant a tampered same-account cached admin role', async () => {
  setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementation(() => new Promise<Response>(() => {})))
  const s = await scope(); setSession({ ...stored('a', 'rotated'), role: 'admin' }); window.dispatchEvent(new StorageEvent('storage', { key: SESSION_STORAGE_KEY })); expect(s.status.value).toBe('authenticated'); expect(s.session.value?.role === 'admin' && s.session.value.roleVerified).toBe(false)
})
it.each(['offline', 'timeout'])('cleans locally with notice after %s logout', async mode => {
  vi.useFakeTimers(); setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementation(() => mode === 'offline' ? Promise.reject(new TypeError('offline')) : new Promise<Response>(() => {})))
  const s = await scope(); const p = s.logout(); await vi.advanceTimersByTimeAsync(5000); await p; expect(s.status.value).toBe('anonymous'); expect(getSession()).toBeNull(); expect(s.notice.value).toContain('本机退出')
})
it('does not let unseen switched storage be erased by a late renewal', async () => {
  vi.useFakeTimers(); setSession(stored('a', 'token-a', Date.now() + 240000)); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementationOnce(() => new Promise<Response>(r => { finish = r })).mockResolvedValue(response(auth('b'))))
  const s = await scope(); await vi.advanceTimersByTimeAsync(60000); setSession(stored('b')); finish(response(auth('a', 'rotated')))
  await vi.advanceTimersByTimeAsync(0); expect(s.session.value?.userId).toBe('b'); expect(getSession()?.userId).toBe('b')
})
it('keeps a rotated session when a historical token reports unauthorized', async () => {
  vi.useFakeTimers(); setSession(stored('a', 'token-a', Date.now() + 240000)); vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => response(auth('a', 'rotated'))))
  const s = await scope(); await vi.advanceTimersByTimeAsync(60000); window.dispatchEvent(new CustomEvent('myink:unauthorized', { detail: { token: 'token-a' } })); expect(s.status.value).toBe('authenticated'); expect(getSession()?.token).toBe('rotated')
})
it('discards a pending login after disposal', async () => {
  let finish!: (r: Response) => void; vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { finish = r })))
  const s = await scope(); const p = s.login('a', 'p'); s.dispose(); finish(response(auth())); expect(await p).toBeNull(); expect(getSession()).toBeNull()
})
it('can renew a new account after an old renewal is aborted without settling', async () => {
  vi.useFakeTimers(); setSession(stored('a', 'token-a', Date.now() + 240000)); let calls = 0
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
    calls++; if (calls === 2) return new Promise<Response>(() => {})
    return response(auth((init.headers as Record<string, string>).Authorization === 'Bearer token-b' ? 'b' : 'a', calls > 3 ? 'renewed-b' : 'token-b'))
  }))
  const s = await scope(); await vi.advanceTimersByTimeAsync(60000); setSession(stored('b', 'token-b', Date.now() + 240000)); await s.revalidate(); await vi.advanceTimersByTimeAsync(60000)
  expect(s.session.value?.token).toBe('renewed-b')
})
it('keeps authenticated status while renewal is pending', async () => {
  vi.useFakeTimers(); setSession(stored('a', 'token-a', Date.now() + 240000)); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementationOnce(() => new Promise<Response>(r => { finish = r })))
  const s = await scope(); await vi.advanceTimersByTimeAsync(60000); expect(s.status.value).toBe('authenticated'); finish(response(auth('a', 'rotated'))); await vi.advanceTimersByTimeAsync(0); expect(s.status.value).toBe('authenticated')
})
it.each([true, false])('does not erase an unseen switched account after logout (success=%s)', async success => {
  setSession(stored()); let finish!: (r: Response) => void; let fail!: (err: Error) => void
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementationOnce(() => new Promise<Response>((resolve, reject) => { finish = resolve; fail = reject })).mockResolvedValue(response(auth('b'))))
  const s = await scope(); const p = s.logout(); setSession(stored('b')); if (success) finish(response({ ok: true })); else fail(new Error('offline')); await p
  expect(getSession()?.userId).toBe('b'); expect(s.session.value?.userId).toBe('b'); expect(s.notice.value).toBeNull()
})
it('preserves a session on wrong MFA and propagates API failures', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'wrong_code' }), { status: 401 })))
  const s = await scope(); await expect(s.completeMfa('ticket', '000000')).rejects.toMatchObject({ code: 'wrong_code' }); expect(s.status.value).toBe('anonymous'); expect(getSession()).toBeNull()
})
it('clears an in-flight logout deadline on disposal', async () => {
  vi.useFakeTimers(); setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementation(() => new Promise<Response>(() => {})))
  const s = await scope(); void s.logout(); await vi.advanceTimersByTimeAsync(0); s.dispose(); expect(vi.getTimerCount()).toBe(0)
})
it('contains storage read failures during an expiry check', async () => {
  vi.useFakeTimers(); setSession(stored('a', 'token-a', Date.now() + 30000)); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(auth())))
  const s = await scope(); vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage disabled') })
  await vi.advanceTimersByTimeAsync(60000); expect(s.status.value).toBe('unavailable')
})
it('contains storage read failures in validation rejection handling', async () => {
  setSession(stored()); let fail!: (e: Error) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((_, reject) => { fail = reject })))
  const s = createSessionScope(); scopes.push(s); const pending = s.start(); vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage disabled') }); fail(new Error('offline'))
  await expect(pending).resolves.toBeUndefined(); expect(s.status.value).toBe('unavailable')
})
it.each([
  ['getItem', 'success'], ['getItem', 'timeout'], ['removeItem', 'success'], ['removeItem', 'timeout'],
] as const)('contains logout storage %s failure after %s without claiming credential removal', async (method, mode) => {
  vi.useFakeTimers(); setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementation(() => mode === 'success' ? Promise.resolve(response({ ok: true })) : new Promise<Response>(() => {})))
  const s = await scope()
  const pending = s.logout()
  const removal = vi.spyOn(Storage.prototype, 'removeItem')
  if (method === 'getItem') vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage disabled') })
  else removal.mockImplementation(() => { throw new Error('storage disabled') })
  const result = pending.then(() => null, err => err)
  await vi.advanceTimersByTimeAsync(5000)
  expect(await result).toBeNull(); expect(s.session.value).toBeNull(); expect(s.status.value).toBe('unavailable')
  expect(s.error.value).toContain('存储'); expect(s.notice.value).toContain('无法确认'); expect(s.notice.value).not.toContain('已仅从本机退出')
  if (method === 'getItem') expect(removal).not.toHaveBeenCalled()
})
it('preserves an unknown newly stored account when logout cannot read storage identity', async () => {
  setSession(stored()); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(auth())).mockImplementationOnce(() => new Promise<Response>(r => { finish = r })))
  const s = await scope(); const pending = s.logout(); setSession(stored('b'))
  const reader = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage disabled') })
  finish(response({ ok: true })); await expect(pending).resolves.toBeUndefined(); expect(s.session.value).toBeNull(); expect(s.status.value).toBe('unavailable')
  reader.mockRestore(); expect(getSession()?.userId).toBe('b')
})
it('contains storage deletion failure after validation returns unauthorized', async () => {
  setSession(stored()); vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 })))
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('storage disabled') })
  const s = createSessionScope(); scopes.push(s)
  await expect(s.start()).resolves.toBeUndefined(); expect(s.session.value).toBeNull(); expect(s.status.value).toBe('unavailable'); expect(s.error.value).toContain('存储'); expect(s.notice.value).toContain('无法确认')
})
it('preserves a newly stored account when an older validation returns unauthorized', async () => {
  setSession(stored()); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise<Response>(r => { finish = r })).mockResolvedValue(response(auth('b'))))
  const s = createSessionScope(); scopes.push(s); const pending = s.start(); setSession(stored('b'))
  const removal = vi.spyOn(Storage.prototype, 'removeItem'); finish(new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401 })); await pending
  expect(s.session.value?.userId).toBe('b'); expect(getSession()?.userId).toBe('b'); expect(removal).not.toHaveBeenCalledWith(SESSION_STORAGE_KEY)
})
