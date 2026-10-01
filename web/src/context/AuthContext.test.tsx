// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { abortRequestsForToken, api } from '../lib/api'
import { dispatchUnauthorized, setSession } from '../lib/token'
import type { AuthSessionResponse } from '../types'
import { AuthProvider, useAuth } from './AuthContext'

vi.mock('../lib/api', () => ({
  abortRequestsForToken: vi.fn(),
  api: {
    login: vi.fn(),
    register: vi.fn(),
    getSession: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn(),
    verifyMfa: vi.fn(),
  },
}))

/** /auth/session 的响应：账号自检信息 + 续期用的新令牌 */
function remoteSession(patch: Partial<AuthSessionResponse> = {}): AuthSessionResponse {
  return {
    user_id: 'user-a', username: 'alice', tier: 'normal', role: 'user',
    token: 'token-a-fresh', expires_in: 1800, ...patch,
  }
}

function Probe() {
  const auth = useAuth()
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="identity">{auth.session?.username ?? 'signed-out'}</span>
      <span data-testid="role">{auth.session?.role ?? 'none'}:{String(auth.session?.roleVerified ?? false)}</span>
      <button type="button" onClick={() => void auth.login(' Alice ', 'correct horse battery')}>login</button>
      <button type="button" onClick={() => void auth.register('Alice', 'correct horse battery', 'invite-123')}>register</button>
      <button type="button" onClick={() => void auth.completeMfa('challenge-a', '123456')}>mfa</button>
      <button type="button" onClick={() => void auth.logout()}>logout</button>
    </div>
  )
}

it('stores the session returned by the second-factor exchange', async () => {
  // 第二因子那一步走的是与登录同一段落会话逻辑：换了令牌、写了 localStorage、状态转 authenticated。
  vi.mocked(api.verifyMfa).mockResolvedValue({
    token: 'token-a', user_id: 'user-a', username: 'root', tier: 'normal', role: 'admin', expires_in: 3600,
  })

  render(<AuthProvider><Probe /></AuthProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'mfa' }))

  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'))
  expect(api.verifyMfa).toHaveBeenCalledWith('challenge-a', '123456')
  expect(screen.getByTestId('identity').textContent).toBe('root')
  expect(screen.getByTestId('role').textContent).toBe('admin:true')
})

it('forwards an invitation for registration without persisting it', async () => {
  vi.mocked(api.register).mockResolvedValue({
    token: 'token-a', user_id: 'user-a', username: 'alice', tier: 'normal', role: 'user', expires_in: 3600,
  })

  render(<AuthProvider><Probe /></AuthProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'register' }))

  await waitFor(() => expect(screen.getByTestId('identity').textContent).toBe('alice'))
  expect(api.register).toHaveBeenCalledWith('Alice', 'correct horse battery', 'invite-123')
  expect(localStorage.getItem('myink.session')).not.toContain('invite-123')
})

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

it('validates a stored session before exposing authenticated content', async () => {
  setSession({
    token: 'cached-token', userId: 'cached-id', username: 'cached-name', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 60_000,
  })
  vi.mocked(api.getSession).mockResolvedValue(remoteSession({
    user_id: 'server-id', username: 'alice', role: 'admin',
  }))

  render(<AuthProvider><Probe /></AuthProvider>)

  expect(screen.getByTestId('status').textContent).toBe('checking')
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'))
  expect(screen.getByTestId('identity').textContent).toBe('alice')
  expect(screen.getByTestId('role').textContent).toBe('admin:true')
  expect(JSON.parse(localStorage.getItem('myink.session') ?? '{}').role).toBe('admin')
  expect(api.getSession).toHaveBeenCalledWith('cached-token', expect.any(AbortSignal))
})

it('uses the canonical account returned by password login', async () => {
  vi.mocked(api.login).mockResolvedValue({
    token: 'token-a', user_id: 'user-a', username: 'alice', tier: 'normal', role: 'user', expires_in: 3600,
  })

  render(<AuthProvider><Probe /></AuthProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'login' }))

  await waitFor(() => expect(screen.getByTestId('identity').textContent).toBe('alice'))
  expect(api.login).toHaveBeenCalledWith(' Alice ', 'correct horse battery')
})

it('discards a late login response after another tab switches accounts', async () => {
  let resolveLogin!: (value: {
    token: string; user_id: string; username: string; tier: string; role: 'user' | 'admin'; expires_in: number
  }) => void
  vi.mocked(api.login).mockReturnValue(new Promise((resolve) => { resolveLogin = resolve }))
  vi.mocked(api.getSession).mockResolvedValue(remoteSession({ user_id: 'user-b', username: 'bob' }))

  render(<AuthProvider><Probe /></AuthProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'login' }))

  const bob = {
    token: 'token-b', userId: 'user-b', username: 'bob', tier: 'normal', role: 'user' as const, roleVerified: true,
    expiresAt: Date.now() + 60_000,
  }
  localStorage.setItem('myink.session', JSON.stringify(bob))
  act(() => {
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'myink.session', newValue: JSON.stringify(bob),
    }))
  })
  await waitFor(() => expect(screen.getByTestId('identity').textContent).toBe('bob'))

  await act(async () => {
    resolveLogin({
      token: 'token-a', user_id: 'user-a', username: 'alice', tier: 'normal', role: 'user', expires_in: 3600,
    })
  })
  expect(screen.getByTestId('identity').textContent).toBe('bob')
})

it('adopts storage instead of letting a late login overwrite an unseen account switch', async () => {
  let resolveLogin!: (value: {
    token: string; user_id: string; username: string; tier: string; role: 'user' | 'admin'; expires_in: number
  }) => void
  vi.mocked(api.login).mockReturnValue(new Promise((resolve) => { resolveLogin = resolve }))
  vi.mocked(api.getSession).mockResolvedValue(remoteSession({ user_id: 'user-b', username: 'bob' }))

  render(<AuthProvider><Probe /></AuthProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'login' }))
  const bob = {
    token: 'token-b', userId: 'user-b', username: 'bob', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 60_000,
  }
  localStorage.setItem('myink.session', JSON.stringify(bob))

  await act(async () => {
    resolveLogin({
      token: 'token-a', user_id: 'user-a', username: 'alice', tier: 'normal', role: 'user', expires_in: 3600,
    })
  })

  await waitFor(() => expect(screen.getByTestId('identity').textContent).toBe('bob'))
  expect(JSON.parse(localStorage.getItem('myink.session') ?? '{}').token).toBe('token-b')
})

it('ignores a delayed unauthorized event from the previous token', async () => {
  const bob = {
    token: 'token-b', userId: 'user-b', username: 'bob', tier: 'normal', role: 'user' as const, roleVerified: true,
    expiresAt: Date.now() + 60_000,
  }
  setSession(bob)
  vi.mocked(api.getSession).mockResolvedValue(remoteSession({ user_id: 'user-b', username: 'bob' }))
  render(<AuthProvider><Probe /></AuthProvider>)
  await waitFor(() => expect(screen.getByTestId('identity').textContent).toBe('bob'))

  act(() => dispatchUnauthorized('token-a'))

  expect(screen.getByTestId('identity').textContent).toBe('bob')
})

it('rotates the token before it expires so an open tab is never signed out', async () => {
  vi.useFakeTimers()
  setSession({
    token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 6 * 60_000,
  })
  vi.mocked(api.getSession).mockResolvedValue(remoteSession({ token: 'token-a-renewed' }))
  await act(async () => { render(<AuthProvider><Probe /></AuthProvider>) })
  expect(screen.getByTestId('status').textContent).toBe('authenticated')

  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })

  expect(JSON.parse(localStorage.getItem('myink.session') ?? '{}').token).toBe('token-a-renewed')
  expect(screen.getByTestId('status').textContent).toBe('authenticated')
  // 换令牌不换账号，所以不能终止在途请求：成稿是一次几分钟的调用，掐它等于写作报错。
  expect(abortRequestsForToken).not.toHaveBeenCalled()
})

it('keeps the session when a renewal attempt fails, and retries on the next cycle', async () => {
  vi.useFakeTimers()
  setSession({
    token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 6 * 60_000,
  })
  vi.mocked(api.getSession).mockResolvedValue(remoteSession())
  await act(async () => { render(<AuthProvider><Probe /></AuthProvider>) })

  // 一次网络抖动不该升级成掉线：登录态不动，等下一个周期再试
  vi.mocked(api.getSession).mockRejectedValue(new Error('network down'))
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(screen.getByTestId('status').textContent).toBe('authenticated')
  expect(JSON.parse(localStorage.getItem('myink.session') ?? '{}').token).toBe('token-a')

  vi.mocked(api.getSession).mockResolvedValue(remoteSession({ token: 'token-a-renewed' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(JSON.parse(localStorage.getItem('myink.session') ?? '{}').token).toBe('token-a-renewed')
})

it('refuses to adopt a session-less renewal response from an older backend', async () => {
  // 滚动发布时前端可能先上：老后端只回身份。此时写进去等于会话里没有 token，
  // getSession() 立刻判无效 → 反而把人登出。宁可这次不续期。
  vi.useFakeTimers()
  setSession({
    token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 6 * 60_000,
  })
  vi.mocked(api.getSession).mockResolvedValue(remoteSession())
  await act(async () => { render(<AuthProvider><Probe /></AuthProvider>) })

  vi.mocked(api.getSession).mockResolvedValue(
    { user_id: 'user-a', username: 'alice', tier: 'normal', role: 'user' } as never,
  )
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })

  expect(screen.getByTestId('identity').textContent).toBe('alice')
  expect(screen.getByTestId('status').textContent).toBe('authenticated')
  expect(JSON.parse(localStorage.getItem('myink.session') ?? '{}').token).toBe('token-a')
})

it('clears an authenticated session when its local expiry arrives un-renewed', async () => {
  vi.useFakeTimers()
  setSession({
    token: 'short-token', userId: 'user-a', username: 'alice', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 50,
  })
  vi.mocked(api.getSession).mockResolvedValue(remoteSession())
  await act(async () => { render(<AuthProvider><Probe /></AuthProvider>) })
  expect(screen.getByTestId('status').textContent).toBe('authenticated')
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(screen.getByTestId('identity').textContent).toBe('signed-out')
  expect(localStorage.getItem('myink.session')).toBeNull()
})

it('does not let a stale renewal erase a newer session written without a storage event', async () => {
  setSession({
    token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 100,
  })
  vi.mocked(api.getSession).mockImplementation(async (token: string) => (token === 'token-a'
    ? remoteSession()
    : remoteSession({ user_id: 'user-b', username: 'bob', token: 'token-b' })))
  render(<AuthProvider><Probe /></AuthProvider>)
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'))

  const bob = {
    token: 'token-b', userId: 'user-b', username: 'bob', tier: 'normal', role: 'user', roleVerified: true,
    expiresAt: Date.now() + 60_000,
  }
  localStorage.setItem('myink.session', JSON.stringify(bob))

  await new Promise((resolve) => { setTimeout(resolve, 150) })
  // 回到前台会立刻补一次续期检查（后台标签页的定时器会被节流）——正是这条路径
  act(() => { document.dispatchEvent(new Event('visibilitychange')) })

  await waitFor(() => expect(screen.getByTestId('identity').textContent).toBe('bob'), { timeout: 1000 })
  expect(JSON.parse(localStorage.getItem('myink.session') ?? '{}').token).toBe('token-b')
})
