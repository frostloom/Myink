import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import App from '../App.vue'
import { createCandidateRouter } from '../router'
import { setSession } from '../../../src/lib/token'

const identity = { user_id: 'alice', username: 'alice', tier: 'pro', role: 'user', token: 'session-token', expires_in: 3600 }
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
async function open(path = '/login') {
  const router = createCandidateRouter(createMemoryHistory())
  await router.push(path); await router.isReady()
  const view = render(App, { global: { plugins: [router] } })
  await screen.findByLabelText('用户名')
  return { router, ...view }
}
async function credentials(name = 'Alice', password = 'oldpass') {
  await fireEvent.update(screen.getByLabelText('用户名'), name)
  await fireEvent.update(screen.getByLabelText('密码'), password)
}
async function register(password = 'abcd1234', confirm = password, invite = 'invite') {
  await fireEvent.click(screen.getByRole('tab', { name: '注册账号' }))
  await credentials('Alice', password)
  await fireEvent.update(screen.getByLabelText('确认密码'), confirm)
  await fireEvent.update(screen.getByLabelText('邀请码'), invite)
  await fireEvent.click(screen.getByRole('button', { name: '创建账号' }))
}
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals() })
it.each([
  ['abcdefgh', 'abcdefgh', 'invite', 'ASCII 字母和 1 个 ASCII 数字'],
  ['abcd1234', 'abcd1235', 'invite', '两次输入的密码不一致'],
  ['abcd1234', 'abcd1234', ' ', '请输入邀请码'],
])('blocks invalid registration before network: %s / %s / %s', async (password, confirm, invite, message) => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher); await open()
  await register(password, confirm, invite)
  expect(screen.getByRole('alert').textContent).toContain(message)
  expect(fetcher).not.toHaveBeenCalled()
})
it('rejects original Unicode username before case folding', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher); await open(); await credentials('Kaa')
  await fireEvent.click(screen.getByRole('button', { name: '登录' }))
  expect(screen.getByRole('alert').textContent).toContain('用户名需为')
  expect(fetcher).not.toHaveBeenCalled()
})
it('normalizes usernames and permits legacy short login passwords', async () => {
  let body: unknown
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/auth/token')) body = JSON.parse(init.body as string)
    return reply(path.endsWith('/projects') ? [] : identity)
  }))
  const { router } = await open(); await credentials(' Alice ', 'a')
  await fireEvent.click(screen.getByRole('button', { name: '登录' }))
  await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/long'))
  expect(body).toEqual({ username: 'alice', password: 'a' })
})
it('submits trimmed invitation without persisting credentials', async () => {
  let body: unknown
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/auth/register')) body = JSON.parse(init.body as string)
    return reply(path.endsWith('/projects') ? [] : identity)
  }))
  const { router } = await open(); await register('abcd1234', 'abcd1234', ' secret-invite ')
  await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/long'))
  expect(body).toEqual({ username: 'alice', password: 'abcd1234', invitation_code: 'secret-invite' })
  expect(JSON.stringify(localStorage)).not.toContain('secret-invite')
  expect(JSON.stringify(localStorage)).not.toContain('abcd1234')
})
it('prevents repeated submit and mode changes while login is pending', async () => {
  let finish!: (r: Response) => void
  const fetcher = vi.fn(() => new Promise<Response>(resolve => { finish = resolve }))
  vi.stubGlobal('fetch', fetcher); await open(); await credentials()
  await fireEvent.submit(screen.getByRole('button', { name: '登录' }).closest('form')!)
  await fireEvent.submit(screen.getByRole('button', { name: '登录中…' }).closest('form')!)
  await fireEvent.click(screen.getByRole('tab', { name: '注册账号' }))
  expect(screen.queryByLabelText('邀请码')).toBeNull()
  expect(fetcher).toHaveBeenCalledTimes(1)
  finish(reply({ error: 'INVALID_CREDENTIALS' }, 401)); await flushPromises()
})
it.each([['INVALID_CREDENTIALS', '用户名或密码不正确'], ['network', '无法连接服务']])('shows a recoverable login error: %s', async (failure, message) => {
  vi.stubGlobal('fetch', vi.fn(async () => { if (failure === 'network') throw new TypeError('offline'); return reply({ error: failure }, 401) }))
  await open(); await credentials(); await fireEvent.click(screen.getByRole('button', { name: '登录' }))
  expect((await screen.findByRole('alert')).textContent).toContain(message)
  expect(screen.getByLabelText('密码')).toBeTruthy()
})
async function mfa() {
  await open(); await credentials(); await fireEvent.click(screen.getByRole('button', { name: '登录' }))
  await screen.findByLabelText('验证码')
}
it('keeps MFA challenge only in memory, validates six digits, and returns to login', async () => {
  const fetcher = vi.fn(async () => reply({ mfa_required: true, mfa_token: 'challenge' }))
  vi.stubGlobal('fetch', fetcher); await mfa()
  expect(screen.queryByLabelText('密码')).toBeNull()
  expect(JSON.stringify(localStorage)).not.toContain('challenge')
  await fireEvent.update(screen.getByLabelText('验证码'), '12345')
  await fireEvent.click(screen.getByRole('button', { name: '验证' }))
  expect(screen.getByRole('alert').textContent).toContain('6 位验证码')
  expect(fetcher).toHaveBeenCalledTimes(1)
  await fireEvent.click(screen.getByRole('button', { name: '返回' }))
  expect(screen.getByLabelText('密码')).toBeTruthy()
  expect(screen.queryByLabelText('验证码')).toBeNull()
})
it('keeps rejected MFA on the code step then exchanges a valid code', async () => {
  let attempts = 0
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/auth/token')) return reply({ mfa_required: true, mfa_token: 'challenge' })
    if (path.endsWith('/auth/mfa/verify')) {
      expect(JSON.parse(init.body as string)).toEqual({ mfa_token: 'challenge', code: attempts === 0 ? '000000' : '123456' })
      return attempts++ === 0 ? reply({ error: 'MFA_INVALID' }, 401) : reply(identity)
    }
    return reply(path.endsWith('/projects') ? [] : identity)
  }))
  await mfa(); await fireEvent.update(screen.getByLabelText('验证码'), '000000'); await fireEvent.click(screen.getByRole('button', { name: '验证' }))
  expect((await screen.findByRole('alert')).textContent).toContain('验证码不正确')
  await fireEvent.update(screen.getByLabelText('验证码'), '123456'); await fireEvent.click(screen.getByRole('button', { name: '验证' }))
  await screen.findByRole('link', { name: '新建长篇' })
})
it('does not navigate from a late login after another tab switches account', async () => {
  let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path.endsWith('/auth/token') ? new Promise<Response>(r => { finish = r }) : reply({ ...identity, user_id: 'bob', username: 'bob', token: 'bob-token' })))
  const { router } = await open(); await credentials(); await fireEvent.click(screen.getByRole('button', { name: '登录' }))
  setSession({ token: 'bob-token', userId: 'bob', username: 'bob', tier: 'pro', role: 'user', roleVerified: false, expiresAt: Date.now() + 3600000 })
  window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' }))
  finish(reply(identity)); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/login')
})
it('does not navigate after the login page unmounts', async () => {
  let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn(async () => new Promise<Response>(r => { finish = r })))
  const { router, unmount } = await open(); await credentials(); await fireEvent.click(screen.getByRole('button', { name: '登录' }))
  unmount(); const pathAfterUnmount = router.currentRoute.value.path
  finish(reply(identity)); await flushPromises()
  expect(router.currentRoute.value.path).toBe(pathAfterUnmount)
})
it('clears an old MFA challenge when another tab changes identity', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path.endsWith('/auth/token')
    ? reply({ mfa_required: true, mfa_token: 'challenge' })
    : reply({ ...identity, user_id: 'bob', username: 'bob', token: 'bob-token' })))
  await mfa()
  setSession({ token: 'bob-token', userId: 'bob', username: 'bob', tier: 'pro', role: 'user', roleVerified: false, expiresAt: Date.now() + 3600000 })
  window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' }))
  await flushPromises()
  expect(screen.queryByLabelText('验证码')).toBeNull()
  expect(screen.getByLabelText('密码')).toBeTruthy()
})
