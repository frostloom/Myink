import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { createMemoryHistory } from 'vue-router'
import { flushPromises } from '@vue/test-utils'
import App from './App.vue'
import { createCandidateRouter } from './router'
import { setSession } from '../../src/lib/token'

const auth = { user_id: 'test', username: 'verified', tier: 'pro', role: 'user', token: 'token', expires_in: 3600 }
function login() { setSession({ token: 'token', userId: 'test', username: 'test', tier: 'pro', role: 'admin', roleVerified: true, expiresAt: Date.now() + 3600000 }) }
async function app(path = '/long') {
  const router = createCandidateRouter(createMemoryHistory()); await router.push(path); await router.isReady()
  render(App, { global: { plugins: [router] } }); return router
}
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals() })
it('does not request project data for an anonymous visitor', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher); await app()
  expect(await screen.findByRole('heading', { name: '长篇' })).toBeTruthy(); expect(fetcher.mock.calls.filter(([url]) => String(url).startsWith('/api/'))).toHaveLength(0)
  await fireEvent.click(screen.getByRole('link', { name: '新建长篇' }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
})
it('shows validation outage with retry rather than claiming the visitor is logged out', async () => {
  login(); vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline'))); await app()
  expect(await screen.findByRole('alert')).toBeTruthy(); expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
  expect(screen.queryByText('请登录后查看作品。')).toBeNull()
})
it('restores verified identity before loading projects and keeps navigation explicit', async () => {
  login(); vi.stubGlobal('fetch', vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/auth/session') ? auth : [{ id: 'book', title: '测试作品', genre: '现实', current_chapter: 1, target_words: 800, creation_status: 'ready' }]))))
  const router = await app(); expect(await within(await screen.findByRole('main')).findByText('测试作品')).toBeTruthy()
  await fireEvent.click(screen.getByRole('link', { name: '新建长篇' }))
  expect(await screen.findByRole('heading', { name: /新建长篇/ })).toBeTruthy(); expect(router.currentRoute.value.path).toBe('/long/new')
})
it.each(['/projects/abc', '/projects/abc/settings', '/projects/abc/lore', '/projects/abc/audit'])('blocks anonymous project route %s before mounting data loaders', async path => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  await app(path)
  expect(await screen.findByText('未登录，无法打开作品。')).toBeTruthy()
  expect(fetcher.mock.calls.filter(([url]) => String(url).startsWith('/api/'))).toHaveLength(0)
})
it.each(['/admin', '/admin/models', '/admin/projects/abc'])('denies server verified ordinary users access to %s', async path => {
  login(); const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => { calls.push(url); return new Response(JSON.stringify(auth)) }))
  await app(path)
  expect(await screen.findByText('只有管理员可以打开控制台。')).toBeTruthy()
  expect(calls).toEqual(['/api/v1/auth/session'])
})

it('does not display the previous account list when its response arrives after switching', async () => {
  login(); let finish!: (r: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    const second = (init.headers as Record<string, string>).Authorization === 'Bearer token-b'
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify(second ? { ...auth, user_id: 'b', username: 'second-user' } : auth))
    if (!second) return new Promise<Response>(r => { finish = r })
    return new Response(JSON.stringify([{ id: 'b-book', title: 'B账号作品', genre: '现实', current_chapter: 0, target_words: 800, creation_status: 'ready' }]))
  }))
  await app(); await vi.waitFor(() => expect(typeof finish).toBe('function'))
  setSession({ token: 'token-b', userId: 'b', username: 'b', tier: 'pro', role: 'user', roleVerified: false, expiresAt: Date.now() + 3600000 })
  window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' }))
  await vi.waitFor(() => expect(within(screen.getByRole('main')).getByText('B账号作品')).toBeTruthy())
  finish(new Response(JSON.stringify([{ id: 'a-book', title: 'A账号旧作品', genre: '现实', current_chapter: 0, target_words: 800, creation_status: 'ready' }])))
  await flushPromises()
  expect(screen.queryByText('A账号旧作品')).toBeNull()
  expect(within(screen.getByRole('main')).getByText('B账号作品')).toBeTruthy()
})

it('opens real login publicly without loading protected data', async () => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  await app('/login')
  expect(await screen.findByLabelText('用户名')).toBeTruthy()
  expect(screen.getByRole('button', { name: '登录' })).toBeTruthy()
  expect(fetcher).not.toHaveBeenCalled()
})
it.each(['user', 'admin'])('navigates to the verified %s home after actual login', async role => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/projects') ? [] : { ...auth, role }))))
  const router = await app('/login')
  await fireEvent.update(await screen.findByLabelText('用户名'), 'Alice')
  await fireEvent.update(screen.getByLabelText('密码'), 'oldpass')
  await fireEvent.click(screen.getByRole('button', { name: '登录' }))
  await vi.waitFor(() => expect(router.currentRoute.value.path).toBe(role === 'admin' ? '/admin' : '/long'))
})
it('chooses root home from server role rather than cached administrator role', async () => {
  login()
  vi.stubGlobal('fetch', vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/auth/session') ? auth : []))))
  const router = await app('/')
  await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/long'))
})
it('keeps login public during a session validation outage', async () => {
  login(); vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
  await app('/login')
  await flushPromises()
  expect(screen.getByLabelText('用户名')).toBeTruthy()
})
it('keeps the mounted protected page when another tab rotates the same account token', async () => {
  login()
  vi.stubGlobal('fetch', vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/auth/session') ? auth : []))))
  await app('/long')
  const page = await screen.findByRole('main')
  setSession({ token: 'new-token', userId: 'test', username: 'verified', tier: 'pro', role: 'user', roleVerified: false, expiresAt: Date.now() + 3600000 })
  window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' }))
  await flushPromises()
  expect(screen.getByRole('main')).toBe(page)
})
it('routes an unknown path to the verified administrator home', async () => {
  login()
  vi.stubGlobal('fetch', vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/auth/session') ? { ...auth, role: 'admin' } : []))))
  const router = await app('/unknown-page')
  await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/admin'))
})
it('allows local logout when cached session verification and remote logout are offline', async () => {
  login()
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
  await app('/long')
  await screen.findByRole('button', { name: '重试' })
  await fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  expect(await screen.findByRole('heading', { name: '长篇' })).toBeTruthy()
  expect(localStorage.getItem('myink.session')).toBeNull()
  expect(screen.getByText(/本地|服务器/)).toBeTruthy()
})
