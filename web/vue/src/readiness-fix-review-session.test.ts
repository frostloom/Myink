import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from '../../src/lib/api'
import { getSession, setSession } from '../../src/lib/token'
import { createSessionScope } from './session'
let scope: ReturnType<typeof createSessionScope> | undefined
const stored = (userId = 'a', token = 'old') => ({ userId, token, username: userId, tier: 'normal', role: 'user' as const, roleVerified: true, expiresAt: Date.now() + 3600000 })
const remote = (userId = 'a', token = 'old') => ({ user_id: userId, token, username: userId, tier: 'normal', role: 'user' as const, expires_in: 3600 })
async function pendingPassword() {
  setSession(stored()); vi.spyOn(api, 'getSession').mockResolvedValue(remote())
  scope = createSessionScope(); await scope.start()
  let finish!: () => void
  vi.spyOn(api, 'changePassword').mockImplementation(() => new Promise(resolve => { finish = () => resolve({ ok: true }) }))
  return { pending: scope.changePassword('password-old', 'password-new'), finish }
}
afterEach(() => { scope?.dispose(); localStorage.clear(); vi.restoreAllMocks() })
it('protects a different account already in storage before its storage event arrives', async () => {
  const { pending, finish } = await pendingPassword()
  setSession(stored('b', 'new-b')); vi.mocked(api.getSession).mockResolvedValue(remote('b', 'new-b'))
  finish(); await pending
  expect(scope!.session.value?.userId).toBe('b'); expect(getSession()?.token).toBe('new-b')
  expect(scope!.notice.value).toBeNull()
})
it('keeps rotated same-owner credentials on offline verification without claiming revocation', async () => {
  const { pending, finish } = await pendingPassword()
  setSession(stored('a', 'rotated')); vi.mocked(api.getSession).mockRejectedValue(new TypeError('offline'))
  finish(); await pending
  expect(scope!.status.value).toBe('authenticated'); expect(getSession()?.token).toBe('rotated')
  expect(scope!.notice.value).toBeNull()
})
it('does not resurrect an account after cross-tab logout during password mutation', async () => {
  const { pending, finish } = await pendingPassword()
  localStorage.clear(); finish(); await pending
  expect(scope!.status.value).toBe('anonymous'); expect(getSession()).toBeNull()
})
it('failed later login does not suppress successful password invalidation', async () => {
  const { pending, finish } = await pendingPassword()
  vi.spyOn(api, 'login').mockRejectedValue(new ApiError(401, 'bad-password', null))
  await expect(scope!.login('a', 'wrong')).rejects.toThrow(); finish(); await pending
  expect(scope!.status.value).toBe('anonymous'); expect(scope!.notice.value).toContain('密码已修改')
})
it('later successful MFA login remains valid when the old password operation finishes', async () => {
  const { pending, finish } = await pendingPassword()
  vi.spyOn(api, 'verifyMfa').mockResolvedValue(remote('a', 'new-mfa'))
  await scope!.completeMfa('ticket', '123456'); finish(); await pending
  expect(scope!.status.value).toBe('authenticated'); expect(getSession()?.token).toBe('new-mfa')
})
it('disposal prevents late password success from clearing stored credentials', async () => {
  const { pending, finish } = await pendingPassword()
  scope!.dispose(); finish(); await pending
  expect(getSession()?.token).toBe('old')
})
