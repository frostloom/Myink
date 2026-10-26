import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ref, type Ref } from 'vue'
import type { Project } from '../../../src/types'
import ProjectRail from './ProjectRail.vue'
import AdminRail from './AdminRail.vue'
const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }))
vi.mock('../authContext', () => ({ useAuth: () => auth.value }))
const projects = [ { id: 'l', title: '长书', form: 'long' }, { id: 's', title: '短书', form: 'short' }, { id: 'd', title: '草稿', form: 'long', creation_status: 'draft' } ].map(p=>({...p,genre:'悬疑',current_chapter:0,target_words:3000})) as Project[]
async function rail(path: string, admin = false, onLogout?: () => void | Promise<void>) {
  auth.value = { session: ref({ username: 'alice', role: 'admin', roleVerified: true }), status: ref('authenticated'), logout: vi.fn() }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/:page?', component: { template: '<div/>' } }, { path: '/:pathMatch(.*)*', component: { template: '<div/>' } }] })
  await router.push(path)
  return render(admin ? AdminRail : ProjectRail, { props: admin ? { onLogout } : { projects, onLogout }, global: { plugins: [router] } })
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
it('hides long book pages in short works and exposes both forms globally', async () => {
  const view = await rail('/projects/s'); expect(screen.queryByRole('link', { name: '设定' })).toBeNull(); view.unmount()
  await rail('/theme'); expect(screen.getByText('长书')).toBeTruthy(); expect(screen.getByText('短书')).toBeTruthy()
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
it('admin navigation marks detail owners and collapses the mobile menu after navigation', async () => {
  await rail('/admin/tasks/task-1', true)
  expect(screen.getByRole('link', { name: '任务' }).getAttribute('aria-current')).toBe('page')
  const toggle = screen.getByText('管理导航').closest('button')!; await fireEvent.click(toggle); expect(toggle.getAttribute('aria-expanded')).toBe('true')
  await fireEvent.click(screen.getByRole('link', { name: '用户' })); expect(toggle.getAttribute('aria-expanded')).toBe('false')
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
