import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { api } from '../../src/lib/api'
import { platformApi } from '../../src/lib/platformApi'
import { adminApi } from '../../src/lib/adminApi'
import { AdminConsole } from './pages/admin/AdminConsole'
import { adminContextKey } from './pages/admin/context'
import type { ChapterMeta } from '../../src/types'
import type { StoredSession } from '../../src/lib/token'
import type { SessionScope } from './session'
import { authKey } from './authContext'
import GenerationPanel from './components/GenerationPanel.vue'
import AdminPage from './pages/AdminPage.vue'
import PlatformConfiguration from './pages/admin/PlatformConfiguration'
vi.mock('../../src/lib/api', async importOriginal => {
  const actual = await importOriginal<typeof import('../../src/lib/api')>()
  return { ...actual, api: { ...actual.api, generateChapter: vi.fn(), generateBatch: vi.fn() } }
})
vi.mock('../../src/lib/platformApi', () => ({ platformApi: { getConfiguration: vi.fn() } }))
const first: ChapterMeta = { id: 'first', chapter_seq: 1, title: '第一章', status: 'confirmed', word_count: 3000, summary: null }
const second: ChapterMeta = { ...first, id: 'second', chapter_seq: 2, title: '第二章' }
const queued = { task_id: 'rewrite-first', trace_id: 'review', status: 'queued' }
beforeEach(() => { vi.mocked(api.generateChapter).mockResolvedValue(queued); vi.mocked(api.generateBatch).mockResolvedValue(queued) })
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks() })
it('keeps the confirmed rewrite chapter while the resource preflight is pending', async () => {
  let finish!: (allowed: boolean) => void
  const beforeGenerate = () => new Promise<boolean>(resolve => { finish = resolve })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const props = { projectId: 'book', chapters: [first, second], selectedChapter: first, onTaskStart: vi.fn(), beforeGenerate }
  const view = render(GenerationPanel, { props })
  await fireEvent.click(screen.getByRole('button', { name: '重写第 1 章' }))
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('重写第 1 章'))
  await view.rerender({ selectedChapter: second })
  finish(true); await flushPromises()
  expect(api.generateChapter).toHaveBeenCalledWith('book', 'first', { seq: 1, rewrite: true, mode: 'auto' })
})
it('reports the submitted rewrite chapter when selection changes before the response', async () => {
  let finish!: (value: typeof queued) => void
  vi.mocked(api.generateChapter).mockReturnValue(new Promise(resolve => { finish = resolve }))
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const onTaskStart = vi.fn()
  const view = render(GenerationPanel, { props: { projectId: 'book', chapters: [first, second], selectedChapter: first, onTaskStart } })
  await fireEvent.click(screen.getByRole('button', { name: '重写第 1 章' }))
  expect(api.generateChapter).toHaveBeenCalledWith('book', 'first', { seq: 1, rewrite: true, mode: 'auto' })
  await view.rerender({ selectedChapter: second })
  finish(queued); await flushPromises()
  expect(onTaskStart).toHaveBeenCalledWith('rewrite-first', undefined, 1, 'auto', 'rewrite')
})
it('preserves an administrator model draft across same-account token renewal', async () => {
  vi.mocked(platformApi.getConfiguration).mockResolvedValue({ version: 4, model_connections: [{ id: 'one', name: '我的模型', protocol: 'openai', base_url: 'https://example.com/v1', model: 'writer-pro', has_api_key: true, enabled: true, user_visible: true }], model_routes: { writer: 'custom:one' }, prompts: {}, genre_packs: {} })
  const session = ref<StoredSession | null>({ token: 'before-renewal', userId: 'admin', username: 'admin', role: 'admin', tier: 'normal', roleVerified: true, expiresAt: null })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/admin', component: AdminPage, children: [{ path: 'models', component: PlatformConfiguration, props: { section: 'models' } }] }] })
  await router.push('/admin/models'); await router.isReady()
  render(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [router], provide: { [authKey as symbol]: { session, status: ref('authenticated'), revalidate: vi.fn(), logout: vi.fn() } as unknown as SessionScope }, stubs: { AdminRail: true } } })
  await fireEvent.click(await screen.findByRole('button', { name: '编辑 我的模型' }))
  await fireEvent.update(screen.getByLabelText('显示名称'), '未保存的后台配置')
  session.value = { ...session.value!, token: 'after-renewal' }
  await flushPromises()
  expect(screen.queryByRole('dialog')).not.toBeNull()
  expect((screen.getByLabelText('显示名称') as HTMLInputElement).value).toBe('未保存的后台配置')
})

it('reads the renewed token when a retained administrator view refreshes', async () => {
  const listUsers = vi.spyOn(adminApi, 'listUsers').mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })
  const token = ref('before-renewal')
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/admin', component: AdminConsole }] })
  await router.push('/admin?tab=users'); await router.isReady()
  render(AdminConsole, { global: { plugins: [router], provide: { [adminContextKey as symbol]: { get token() { return token.value }, onForbidden: vi.fn() } } } })
  await flushPromises()
  expect(listUsers.mock.calls[0][0]).toBe('before-renewal')
  token.value = 'after-renewal'
  await flushPromises()
  await fireEvent.click(screen.getByRole('button', { name: '刷新当前视图' }))
  await flushPromises()
  expect(listUsers.mock.calls.at(-1)?.[0]).toBe('after-renewal')
})

it.each(['next', 'batch'] as const)('keeps the %s request snapshot across resource checks and the response', async action => {
  let approve!: (allowed: boolean) => void
  let finish!: (value: typeof queued) => void
  const result = new Promise<typeof queued>(resolve => { finish = resolve })
  if (action === 'next') vi.mocked(api.generateChapter).mockReturnValue(result)
  else vi.mocked(api.generateBatch).mockReturnValue(result)
  const onTaskStart = vi.fn()
  const view = render(GenerationPanel, { props: { projectId: 'book', chapters: [first], selectedChapter: first, onTaskStart, beforeGenerate: () => new Promise<boolean>(resolve => { approve = resolve }) } })
  await fireEvent.update(screen.getByLabelText('写作指令（可留空）'), '已提交的指令')
  await fireEvent.click(screen.getByRole('button', { name: action === 'next' ? '写下一章（第 2 章）' : '发起批次' }))
  await fireEvent.update(screen.getByLabelText('写作指令（可留空）'), '之后编辑的指令')
  await fireEvent.update(screen.getByLabelText('批次生成'), '7')
  await view.rerender({ chapters: [first, second] })
  approve(true); await flushPromises()
  if (action === 'next') expect(api.generateChapter).toHaveBeenCalledWith('book', 'first', { seq: 2, mode: 'auto', user_instruction: '已提交的指令' })
  else expect(api.generateBatch).toHaveBeenCalledWith('book', { size: 3, start: 2 })
  await view.rerender({ chapters: [first, second, { ...second, id: 'third', chapter_seq: 3 }] })
  await fireEvent.update(screen.getByLabelText('批次生成'), '9')
  finish(queued); await flushPromises()
  expect(onTaskStart).toHaveBeenCalledWith('rewrite-first', action === 'batch' ? 3 : undefined, 2, ...(action === 'next' ? ['auto'] : []))
  expect(screen.getByRole('status').textContent).toContain(action === 'next' ? '第 2 章写作任务已创建' : '从第 2 章开始写作')
})

it('does not report a rewrite after its account-owned component is disposed', async () => {
  let finish!: (value: typeof queued) => void
  vi.mocked(api.generateChapter).mockReturnValue(new Promise(resolve => { finish = resolve }))
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const onTaskStart = vi.fn()
  const view = render(GenerationPanel, { props: { projectId: 'book', chapters: [first], selectedChapter: first, onTaskStart } })
  await fireEvent.click(screen.getByRole('button', { name: '重写第 1 章' }))
  view.unmount(); finish(queued); await flushPromises()
  expect(onTaskStart).not.toHaveBeenCalled()
})
