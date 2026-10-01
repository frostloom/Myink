// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

it('sends username and password to the token endpoint', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    token: 'token-a',
    user_id: 'user-a',
    username: 'alice',
    tier: 'normal',
    expires_in: 3600,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)

  await api.login('Alice', 'correct horse battery')

  expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/token', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ username: 'Alice', password: 'correct horse battery' }),
  }))
})

it('sends the invitation only with registration credentials', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    token: 'token-a', user_id: 'user-a', username: 'alice', tier: 'normal', expires_in: 3600,
  }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)

  await api.register('alice', 'correct horse battery', 'invite-code-123')

  expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/register', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({
      username: 'alice',
      password: 'correct horse battery',
      invitation_code: 'invite-code-123',
    }),
  }))
})

it('does not globally sign out when the current password is rejected', async () => {
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-b', userId: 'user-b', username: 'bob', tier: 'normal', expiresAt: Date.now() + 60_000,
  }))
  const events = vi.fn()
  window.addEventListener('myink:unauthorized', events)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ error: 'INVALID_CREDENTIALS' }),
    { status: 401, headers: { 'Content-Type': 'application/json' } },
  )))

  await expect(api.changePassword('wrong password', 'a much better password', 'token-b')).rejects.toMatchObject({
    status: 401,
    code: 'INVALID_CREDENTIALS',
  })
  expect(events).not.toHaveBeenCalled()
  window.removeEventListener('myink:unauthorized', events)
})

it('returns the challenge body untouched when the account needs a second factor', async () => {
  // 密码对了但账号开了第二因子：回的是挑战票不是令牌。api.login 的联合类型靠 mfa_required 判别。
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    mfa_required: true, mfa_token: 'challenge-a', expires_in: 300,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } })))

  const resp = await api.login('root', 'correct horse battery')

  expect('mfa_required' in resp).toBe(true)
  expect(resp).toEqual({ mfa_required: true, mfa_token: 'challenge-a', expires_in: 300 })
})

it('exchanges the challenge ticket for a token without sending any bearer', async () => {
  // 本机可能正躺着一张旧令牌（比如开着第二因子之前的会话）。验码这一步必须不带它：
  // 挑战票自己对不上任何令牌，带上只会让服务端按别的账号的请求处理。
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-stale', userId: 'user-b', username: 'bob', tier: 'normal', expiresAt: Date.now() + 60_000,
  }))
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    token: 'token-a', user_id: 'user-a', username: 'root', tier: 'normal', role: 'admin', expires_in: 3600,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)

  await api.verifyMfa('challenge-a', '123456')

  const [, init] = fetchMock.mock.calls[0] as [string, { headers: Record<string, string> }]
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/mfa/verify', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ mfa_token: 'challenge-a', code: '123456' }),
  }))
  expect(init.headers.Authorization).toBeUndefined()
})

it('sends the current password when enrolling a second factor', async () => {
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-a', userId: 'user-a', username: 'root', tier: 'normal', expiresAt: Date.now() + 60_000,
  }))
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/Myink:root?secret=JBSWY3DPEHPK3PXP',
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)

  await api.mfaEnroll('correct horse battery', 'token-a')

  expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/mfa/enroll', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ password: 'correct horse battery' }),
  }))
})

it('does not globally sign out when a second-factor code is rejected', async () => {
  // 输错一次验证码是 401，但那是「这一步没过」不是「登录态失效」——全局登出在这会把人踢回
  // 登录页，反而要多输一次密码。
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-b', userId: 'user-b', username: 'bob', tier: 'normal', expiresAt: Date.now() + 60_000,
  }))
  const events = vi.fn()
  window.addEventListener('myink:unauthorized', events)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ error: 'MFA_INVALID' }),
    { status: 401, headers: { 'Content-Type': 'application/json' } },
  )))

  await expect(api.mfaConfirm('000000', 'token-b')).rejects.toMatchObject({
    status: 401, code: 'MFA_INVALID',
  })
  expect(events).not.toHaveBeenCalled()
  window.removeEventListener('myink:unauthorized', events)
})

it('discards a successful protected response after the browser switches tokens', async () => {
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', expiresAt: Date.now() + 60_000,
  }))
  let resolveBody!: (value: unknown) => void
  const body = new Promise((resolve) => { resolveBody = resolve })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => body,
  }))

  const pending = api.listProjects()
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-b', userId: 'user-b', username: 'bob', tier: 'normal', expiresAt: Date.now() + 60_000,
  }))
  resolveBody([])

  await expect(pending).rejects.toMatchObject({ code: 'request_aborted' })
})

it('keeps a protected response when renewal rotates the token of the same account', async () => {
  // 滑动续期后台每半小时换一次令牌。若按令牌字符串判过时，正在跑的请求会在那一刻
  // 被判成 aborted——生成中的写操作会报错，而成稿是一次几分钟的调用。
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', expiresAt: Date.now() + 60_000,
  }))
  let resolveBody!: (value: unknown) => void
  const body = new Promise((resolve) => { resolveBody = resolve })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => body,
  }))

  const pending = api.listProjects()
  localStorage.setItem('myink.session', JSON.stringify({
    token: 'token-a-renewed', userId: 'user-a', username: 'alice', tier: 'normal',
    expiresAt: Date.now() + 1_800_000,
  }))
  resolveBody([])

  await expect(pending).resolves.toEqual([])
})
