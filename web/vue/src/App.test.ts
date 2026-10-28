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
it.each(['/', '/unknown-page'])('opens the login entry for an anonymous visit to %s', async path => {
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  const router = await app(path)
  expect(await screen.findByLabelText('用户名')).toBeTruthy()
  expect(router.currentRoute.value.path).toBe('/login')
  expect(screen.getByRole('button', { name: '游客体验' })).toBeTruthy()
  expect(screen.queryByRole('heading', { name: '长篇' })).toBeNull()
  expect(fetcher).not.toHaveBeenCalled()
})
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

it('keeps the same navigation and scroll while the next page waits for its book list', async () => {
  login()
  let delayed = false
  let finish!: (r: Response) => void
  const books = [{ id: 'book', title: '持续显示的作品', form: 'long', genre: '现实', current_chapter: 1, target_words: 800, creation_status: 'ready' }]
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify(auth))
    if (path.endsWith('/projects')) return delayed ? new Promise<Response>(resolve => { finish = resolve }) : new Response(JSON.stringify(books))
    return new Response(JSON.stringify({}))
  }))
  const router = await app()
  const navigation = await screen.findByRole('navigation', { name: '作品列表' })
  await within(navigation).findByText('持续显示的作品')
  const rail = navigation.closest('aside')!
  rail.scrollTop = 180
  delayed = true
  await router.push('/projects/book/settings')
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  expect(screen.getByRole('navigation', { name: '作品列表' })).toBe(navigation)
  expect(within(navigation).getByText('持续显示的作品')).toBeTruthy()
  expect(rail.scrollTop).toBe(180)
  finish(new Response(JSON.stringify(books)))
  await flushPromises()
  expect(screen.getByRole('navigation', { name: '作品列表' })).toBe(navigation)
})

it('clears a loaded navigation list immediately at the account boundary', async () => {
  login()
  let finishB!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    const second = (init.headers as Record<string, string>).Authorization === 'Bearer token-b'
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify(second ? { ...auth, user_id: 'b', username: 'second-user' } : auth))
    if (second) return new Promise<Response>(resolve => { finishB = resolve })
    return new Response(JSON.stringify([{ id: 'a', title: '上一账号的书', creation_status: 'ready' }]))
  }))
  await app()
  await within(await screen.findByRole('navigation', { name: '作品列表' })).findByText('上一账号的书')
  setSession({ token: 'token-b', userId: 'b', username: 'b', tier: 'pro', role: 'user', roleVerified: false, expiresAt: Date.now() + 3600000 })
  window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' }))
  await vi.waitFor(() => expect(finishB).toBeTypeOf('function'))
  expect(screen.queryByText('上一账号的书')).toBeNull()
  finishB(new Response(JSON.stringify([])))
  await flushPromises()
  expect(within(screen.getByRole('navigation', { name: '作品列表' })).queryAllByRole('link')).toHaveLength(0)
})

it('removes the last deleted book from the persistent navigation', async () => {
  login()
  let deleted = false
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify(auth))
    if (init.method === 'DELETE') { deleted = true; return new Response(JSON.stringify({ ok: true })) }
    return new Response(JSON.stringify(deleted ? [] : [{ id: 'book', title: '最后一本', genre: '现实', current_chapter: 0, target_words: 800, creation_status: 'ready' }]))
  }))
  await app()
  const navigation = await screen.findByRole('navigation', { name: '作品列表' })
  await within(navigation).findByText('最后一本')
  await fireEvent.click(screen.getByRole('button', { name: /删除/ }))
  await vi.waitFor(() => expect(within(navigation).queryByText('最后一本')).toBeNull())
  expect(screen.getByRole('navigation', { name: '作品列表' })).toBe(navigation)
  vi.mocked(window.confirm).mockRestore()
})

it('retains the user navigation instance when visiting and leaving the admin area', async () => {
  login()
  vi.stubGlobal('fetch', vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/auth/session') ? auth : []))))
  const router = await app()
  const navigation = await screen.findByRole('navigation', { name: '作品列表' })
  const rail = navigation.closest('aside')!
  rail.scrollTop = 90
  await router.push('/admin')
  await flushPromises()
  expect(screen.queryByRole('navigation', { name: '作品列表' })).toBeNull()
  await router.push('/long')
  await flushPromises()
  expect(screen.getByRole('navigation', { name: '作品列表' })).toBe(navigation)
  expect(rail.scrollTop).toBe(90)
})

it('shows only one persistent admin rail across account and admin routes', async () => {
  login()
  vi.stubGlobal('fetch', vi.fn(async (path: string) => new Response(JSON.stringify(path.endsWith('/auth/session') ? { ...auth, role: 'admin' } : []))))
  const router = await app('/account')
  const navigation = await screen.findByRole('navigation', { name: '平台管理导航' })
  const projectAside = screen.getByRole('navigation', { name: '作品列表', hidden: true }).closest('aside')!
  expect(getComputedStyle(projectAside).display).toBe('none')
  expect([...document.querySelectorAll('aside')].filter(aside => getComputedStyle(aside).display !== 'none')).toHaveLength(1)
  expect(screen.queryByRole('navigation', { name: '作品列表' })).toBeNull()
  const rail = navigation.closest('aside')!
  rail.scrollTop = 140
  await router.push('/admin')
  await flushPromises()
  expect(screen.getByRole('navigation', { name: '平台管理导航' })).toBe(navigation)
  expect(rail.scrollTop).toBe(140)
  expect(getComputedStyle(projectAside).display).toBe('none')
  expect([...document.querySelectorAll('aside')].filter(aside => getComputedStyle(aside).display !== 'none')).toHaveLength(1)
  await router.push('/account')
  await flushPromises()
  expect(screen.getByRole('navigation', { name: '平台管理导航' })).toBe(navigation)
  expect(screen.queryByRole('navigation', { name: '作品列表' })).toBeNull()
})

it('keeps a short conversation and its next draft while navigating during a real pending request', async () => {
  login()
  let finish!: (response: Response) => void
  let requestSignal!: AbortSignal
  const conversation = { session: { id: 's1', status: 'active', card: {}, style_item_id: null, book_id: null }, messages: [], sessions: [], ready: false }
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify(auth))
    if (path.endsWith('/messages')) { requestSignal = init.signal!; return new Promise<Response>(resolve => { finish = resolve }) }
    if (path.endsWith('/short/creation')) return new Response(JSON.stringify(conversation))
    if (path.includes('style')) return new Response(JSON.stringify({ items: [] }))
    return new Response(JSON.stringify([]))
  }))
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const router = await app('/short/new')
  await fireEvent.update(await screen.findByLabelText('对助手说'), '第一条消息')
  await fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  await fireEvent.update(screen.getByLabelText('对助手说'), '下一条草稿')
  await router.push('/long')
  expect(router.currentRoute.value.path).toBe('/long')
  expect(requestSignal.aborted).toBe(false)
  await router.push('/short/new')
  expect(await screen.findByText('正在努力构思中，请稍后')).toBeTruthy()
  expect((screen.getByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('下一条草稿')
  await router.push('/long')
  finish(new Response(JSON.stringify({ ...conversation, messages: [{ id: 1, role: 'assistant', content: '后台回复完成' }] })))
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/long')
  await router.push('/short/new')
  expect(await screen.findByText('后台回复完成')).toBeTruthy()
  expect((screen.getByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('下一条草稿')
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

it.each(['account', 'role', 'logout'])('discards the cached short conversation and aborts its request at the %s boundary', async boundary => {
  login()
  let finish!: (response: Response) => void
  let requestSignal!: AbortSignal
  let changed = false
  const conversation = { session: { id: 's1', status: 'active', card: {} }, messages: [], sessions: [], ready: false }
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify(changed ? { ...auth, user_id: boundary === 'account' ? 'b' : 'test', role: boundary === 'role' ? 'admin' : 'user' } : auth))
    if (path.endsWith('/messages')) { requestSignal = init.signal!; return new Promise<Response>(resolve => { finish = resolve }) }
    if (path.endsWith('/short/creation')) return new Response(JSON.stringify(conversation))
    if (path.includes('style')) return new Response(JSON.stringify({ items: [] }))
    return new Response(JSON.stringify([]))
  }))
  const router = await app('/short/new')
  await fireEvent.update(await screen.findByLabelText('对助手说'), '旧身份消息')
  await fireEvent.click(screen.getByRole('button', { name: '发送' }))
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
  await fireEvent.update(screen.getByLabelText('对助手说'), '旧身份草稿')
  await router.push('/long')
  changed = true
  if (boundary === 'logout') localStorage.removeItem('myink.session')
  else setSession({ token: 'token-b', userId: boundary === 'account' ? 'b' : 'test', username: 'new', tier: 'pro', role: 'user', roleVerified: false, expiresAt: Date.now() + 3600000 })
  window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' }))
  await vi.waitFor(() => expect(requestSignal.aborted).toBe(true))
  finish(new Response(JSON.stringify({ ...conversation, messages: [{ id: 1, role: 'assistant', content: '旧身份迟到消息' }] })))
  await flushPromises()
  await router.push('/short/new')
  if (boundary !== 'logout') expect((await screen.findByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('')
  expect(screen.queryByText('旧身份迟到消息')).toBeNull()
})

it.each(['confirm', 'expiry'])('protects a retained short draft when manually opening login would destroy its cache, then allows %s', async resolution => {
  login()
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    if (path.endsWith('/auth/session')) return new Response(JSON.stringify(auth))
    if (path.endsWith('/short/creation')) return new Response(JSON.stringify({ session: { id: 's1', status: 'active', card: {} }, messages: [], sessions: [], ready: false }))
    if (path.includes('style')) return new Response(JSON.stringify({ items: [] }))
    return new Response(JSON.stringify([]))
  }))
  const router = await app('/short/new')
  await fireEvent.update(await screen.findByLabelText('对助手说'), '不能丢失的短篇草稿')
  await router.push('/long')
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await router.push('/login')
  expect(router.currentRoute.value.path).toBe('/long')
  expect(confirm).toHaveBeenCalledTimes(1)
  await router.push('/short/new')
  expect((await screen.findByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('不能丢失的短篇草稿')
  confirm.mockClear()
  if (resolution === 'expiry') {
    localStorage.removeItem('myink.session')
    window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' }))
    await flushPromises()
  } else confirm.mockReturnValue(true)
  await router.push('/login')
  expect(router.currentRoute.value.path).toBe('/login')
  expect(confirm).toHaveBeenCalledTimes(resolution === 'expiry' ? 0 : 1)
  confirm.mockRestore()
})
