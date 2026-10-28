import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ref, type Ref } from 'vue'
import type { Project } from '../../../src/types'
import { api } from '../../../src/lib/api'
import ProjectRail from './ProjectRail.vue'
import AdminRail from './AdminRail.vue'
const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }))
vi.mock('../authContext', () => ({ useAuth: () => auth.value }))
const projects = [ { id: 'l', title: '长书', form: 'long' }, { id: 's', title: '短书', form: 'short' }, { id: 'd', title: '草稿', form: 'long', creation_status: 'draft' } ].map(p=>({...p,genre:'悬疑',current_chapter:0,target_words:3000})) as Project[]
async function rail(path: string, admin = false, onLogout?: () => void | Promise<void>) {
  auth.value = { session: ref({ username: 'alice', role: 'admin', roleVerified: true }), status: ref('authenticated'), logout: vi.fn() }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/:page?', component: { template: '<div/>' } }, { path: '/:pathMatch(.*)*', component: { template: '<div/>' } }] })
  await router.push(path)
  return { ...render(admin ? AdminRail : ProjectRail, { props: admin ? { onLogout } : { projects, onLogout }, global: { plugins: [router] } }), router }
}
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('filters drafts and sections while exposing long book pages and active mode', async () => {
  await rail('/projects/l/settings')
  expect(screen.getByRole('link', { name: '长篇' }).getAttribute('aria-current')).toBe('true')
  expect(within(screen.getByRole('navigation', { name: '作品列表' })).queryByText('短书')).toBeNull()
  expect(screen.queryByText('草稿')).toBeNull()
  expect(screen.getByRole('link', { name: '设定' })).toBeTruthy()
  expect(screen.queryByRole('link', { name: '主题' })).toBeNull()
})
it('hides long book pages in short works and defaults a new global navigation to long works', async () => {
  const view = await rail('/projects/s'); expect(screen.queryByRole('link', { name: '设定' })).toBeNull(); view.unmount()
  await rail('/theme'); expect(screen.getByText('长书')).toBeTruthy(); expect(screen.queryByText('短书')).toBeNull()
  expect(screen.getByRole('link', { name: '短篇' }).hasAttribute('aria-current')).toBe(false)
  expect(screen.getByRole('link', { name: '文风库' })).toBeTruthy()
})
it('gates admin and feedback on verified authentication and dispatches mobile feedback', async () => {
  await rail('/long'); const seen = vi.fn(); window.addEventListener('myink:feedback', seen)
  await fireEvent.click(screen.getByText('反馈')); expect(seen).toHaveBeenCalledOnce(); window.removeEventListener('myink:feedback', seen)
  expect(screen.getByRole('link', { name: '管理后台' })).toBeTruthy()
  ;(auth.value.session as Ref<{roleVerified:boolean}>).value.roleVerified = false
  await vi.waitFor(() => expect(screen.queryByRole('link', { name: '管理后台' })).toBeNull())
  ;(auth.value.status as ReturnType<typeof ref>).value = 'anonymous'
  await vi.waitFor(() => expect(screen.queryByText('反馈')).toBeNull())
  expect(screen.getByRole('link', { name: '登录' })).toBeTruthy()
})
it('admin navigation is directly available and marks detail owners', async () => {
  await rail('/admin/tasks/task-1', true)
  expect(screen.getByRole('link', { name: '任务' }).getAttribute('aria-current')).toBe('page')
  expect(screen.queryByText('管理导航')).toBeNull()
  expect(screen.getByRole('link', { name: '用户' })).toBeTruthy()
  await fireEvent.click(screen.getByRole('button', { name: '退出登录' })); expect(auth.value.logout).toHaveBeenCalledOnce()
})

it.each([false, true])('invokes an explicit logout handler once for admin=%s', async admin => {
  const onLogout = vi.fn(async () => {})
  await rail(admin ? '/admin' : '/long', admin, onLogout)
  await fireEvent.click(screen.getByRole('button', { name: admin ? '退出登录' : '登出' }))
  expect(onLogout).toHaveBeenCalledOnce()
  expect(auth.value.logout).not.toHaveBeenCalled()
})
it('uses the authentication logout once when ProjectRail has no explicit handler', async () => {
  await rail('/long')
  await fireEvent.click(screen.getByRole('button', { name: '登出' }))
  expect(auth.value.logout).toHaveBeenCalledOnce()
})

it('places long-story resource editing in creation settings',async()=>{
 await rail('/projects/l')
 expect(screen.getByRole('link',{name:'创作设置'}).getAttribute('href')).toBe('/projects/l/settings')
 expect(screen.queryByRole('link',{name:'写作资源'})).toBeNull()
})
it('does not expose book resource pages for short stories',async()=>{
 await rail('/projects/s')
 expect(screen.queryByRole('link',{name:'写作资源'})).toBeNull()
 expect(screen.queryByRole('navigation',{name:'本书页面'})).toBeNull()
})
it('places the personal resource library after the style library',async()=>{
 await rail('/long')
 expect(screen.getByRole('link',{name:'写作资源'}).getAttribute('href')).toBe('/writing-resources')
})

it('removes admin actions immediately when the session becomes anonymous', async () => {
  await rail('/admin', true)
  ;(auth.value.status as ReturnType<typeof ref>).value = 'anonymous'
  await vi.waitFor(() => expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull())
  expect(screen.queryByRole('link', { name: '用户' })).toBeNull()
  expect(screen.getByRole('link', { name: '登录' })).toBeTruthy()
})

it('moves page resource actions into the persistent rail and removes them on unmount', async () => {
  const { persistentRailKey } = await import('../navigationContext')
  auth.value = { session: ref({ userId: 'a', username: 'alice' }), status: ref('authenticated'), logout: vi.fn() }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId', component: { template: '<div />' } }] })
  await router.push('/projects/l')
  const visible = ref(true)
  render({
    components: { ProjectRail },
    setup: () => ({ projects, visible }),
    template: '<ProjectRail :projects="projects" persistent /><ProjectRail v-if="visible" :projects="projects"><template #resource-actions><button>检查资源更新</button></template></ProjectRail>',
  }, { global: { plugins: [router], provide: { [persistentRailKey as symbol]: true } } })
  const action = screen.getByRole('button', { name: '检查资源更新' })
  const rail = screen.getByRole('navigation', { name: '作品列表' }).closest('aside')!
  expect(rail.contains(action)).toBe(true)
  visible.value = false
  await vi.waitFor(() => expect(screen.queryByRole('button', { name: '检查资源更新' })).toBeNull())
  expect(screen.getByRole('navigation', { name: '作品列表' }).closest('aside')).toBe(rail)
})

it.each([false, true])('hides the real rail DOM with the visible prop for admin=%s', async admin => {
  const view = await rail(admin ? '/admin' : '/long', admin)
  const aside = view.container.querySelector('aside')!
  expect(getComputedStyle(aside).display).not.toBe('none')
  await view.rerender({ visible: false })
  expect(view.container.querySelector('aside')).toBe(aside)
  expect(getComputedStyle(aside).display).toBe('none')
  await view.rerender({ visible: true })
  expect(view.container.querySelector('aside')).toBe(aside)
  expect(getComputedStyle(aside).display).not.toBe('none')
})

it.each([
  ['/long', '/theme', '长篇', '长书', '短书'],
  ['/short', '/styles', '短篇', '短书', '长书'],
  ['/projects/s', '/theme', '短篇', '短书', '长书'],
])('retains the selected section from %s to %s', async (from, to, section, book, otherBook) => {
  const view = await rail(from)
  const list = screen.getByRole('navigation', { name: '作品列表' })
  await view.router.push(to)
  expect(screen.getByRole('navigation', { name: '作品列表' })).toBe(list)
  expect(within(list).getByText(book)).toBeTruthy()
  expect(within(list).queryByText(otherBook)).toBeNull()
  expect(screen.getByRole('link', { name: section }).getAttribute('aria-current')).toBe('true')
})

it('resets the remembered section when the account rail is remounted', async () => {
  const previous = await rail('/short')
  await previous.router.push('/styles')
  expect(screen.getByRole('link', { name: '短篇' }).getAttribute('aria-current')).toBe('true')
  previous.unmount()
  await rail('/styles')
  expect(screen.getByRole('link', { name: '长篇' }).getAttribute('aria-current')).toBe('true')
  expect(screen.queryByText('短书')).toBeNull()
})

it('updates the remembered section when a delayed book list identifies a short work', async () => {
  const view = await rail('/long')
  await view.rerender({ projects: [] })
  await view.router.push('/projects/s')
  expect(screen.getByRole('link', { name: '长篇' }).getAttribute('aria-current')).toBe('true')
  await view.rerender({ projects })
  expect(screen.getByRole('link', { name: '短篇' }).getAttribute('aria-current')).toBe('true')
  await view.router.push('/theme')
  expect(screen.getByRole('link', { name: '短篇' }).getAttribute('aria-current')).toBe('true')
  expect(screen.queryByText('长书')).toBeNull()
})


it.each([
  { isGuest: true, username: 'guest-20c3a959b4914b958f058f5001d8488a', label: '游客' },
  { isGuest: false, username: 'alice', label: 'alice' },
])('shows the appropriate account label for isGuest=$isGuest', async ({ isGuest, username, label }) => {
  vi.spyOn(api, 'guestQuota').mockResolvedValue({
    short: { limit: 2, used: 1, remaining: 1 }, long: { limit: 10, used: 3, remaining: 7 },
  })
  await rail('/long')
  ;(auth.value.session as Ref).value = { userId: 'g', username, isGuest, role: 'user', roleVerified: true }
  const logout = screen.getByRole('button', { name: '登出' })
  await vi.waitFor(() => expect(within(logout.parentElement!).getByText(label, { exact: true })).toBeTruthy())
  if (isGuest) expect(screen.queryByText(username, { exact: true })).toBeNull()
  await fireEvent.click(logout)
  expect(auth.value.logout).toHaveBeenCalledOnce()
})
