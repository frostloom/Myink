/* eslint-disable vue/one-component-per-file -- Router and resource-dialog test harnesses. */
// @vitest-environment jsdom
import {  cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter, RouterView, useRouter as currentRouter } from 'vue-router'
import { defineComponent, h, ref } from 'vue'
const act = async (fn: () => unknown) => { await fn(); await Promise.resolve() }
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NewProjectPage from './NewProjectPage.vue'
import { api } from '../../../src/lib/api'
import { writingResources as writingResourcesApi } from '../../../src/lib/writingResources'
import { emptyFields } from '../../../src/lib/genrePacks'
import { styleLibraryApi } from '../../../src/lib/styleLibraryApi'
import type { OutlineDraft, ProjectCreation } from '../../../src/types'

const creationStatus = ref('authenticated')
vi.mock('../../../src/lib/writingResources', () => ({ writingResources: { snapshot: vi.fn(), select: vi.fn() } }))
vi.mock('../components/CreationResourcesDialog.vue', () => ({ default: defineComponent({ props: { busy: Boolean, error: {type: String, default: ''} }, emits: ['confirm', 'close'], setup(props, { emit }) { return () => h('div', { role: 'dialog', 'aria-label': '选择写作资源' }, [props.error && h('p', { role: 'alert' }, props.error), h('button', { disabled: props.busy, onClick: () => emit('confirm', [{ origin: 'platform', resource_id: 'style-1' }]) }, '确认资源并创建作品'), h('button', { disabled: props.busy, onClick: () => emit('close') }, '取消资源选择')]) } }) }))
beforeEach(() => {
  vi.mocked(writingResourcesApi.snapshot).mockResolvedValue({ revision: 4, configured: false, selections: [] })
  vi.mocked(writingResourcesApi.select).mockResolvedValue({ revision: 5, configured: true, selections: [] })
})
vi.mock('../authContext', () => ({ useAuth: () => ({ session: ref(null), status: creationStatus, logout: vi.fn() }) }))
vi.mock('../components/RankingsPanel.vue', () => ({ default: { render: () => null } }))
vi.mock('../components/ProjectRail.vue', () => ({ default: { render: () => null } }))
vi.mock('../../../src/lib/styleLibraryApi', () => ({
  styleLibraryApi: { resources: vi.fn().mockResolvedValue({ items: [] }) },
}))
vi.mock('../../../src/lib/api', async (original) => ({
  ...await original<typeof import('../../../src/lib/api')>(),
  api: { listGenrePacks: vi.fn().mockResolvedValue([]), listProjects: vi.fn().mockResolvedValue([]),
    getCreation: vi.fn(), createProject: vi.fn(), setupDraft: vi.fn(), outlineDraft: vi.fn(),
    updateProject: vi.fn(), confirmSetup: vi.fn(), confirmOutline: vi.fn() },
}))
afterEach(() => {
  cleanup()
  creationStatus.value = 'authenticated'
  sessionStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

const NavigationControls = defineComponent({ setup() { const router = currentRouter(); return () => h('div', [h('button', { onClick: () => router.push('/projects/new') }, 'new-project'), h('button', { onClick: () => router.push('/projects/new?draft=draft-b') }, 'draft-b')]) } })
async function renderPage(initialEntry = '/projects/new') {
  const page = { render: () => h('div', [h(NewProjectPage), h(NavigationControls)]) }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/projects/new', component: page },
    { path: '/long/new', component: NewProjectPage, props: { form: 'long' } },
    { path: '/short/new', component: NewProjectPage, props: { form: 'short' } },
    { path: '/projects/:id/resources', component: { render: () => h('div', '资源页') } },
    { path: '/projects/:id', component: { render: () => h('div', '工作台') } },
    { path: '/long', component: { render: () => h('div', '长篇库') } },
  ] })
  await router.push(initialEntry); await router.isReady()
  return { ...render(RouterView, { global: { plugins: [router] } }), router }
}

async function fillCreationBrief() {
  await fireEvent.input(screen.getByLabelText('创作简报'), { target: { value: '寻找真相' } })
}

it('restores an unfinished book without creating a duplicate or exposing a skip button', async () => {
  vi.mocked(api.getCreation).mockResolvedValue({
    project: { id: 'draft-id', title: '我的草稿', genre: '悬疑', current_chapter: 0,
      target_words: 3000, creation_status: 'setup_confirmed' },
    context: { premise: '尚未写完的创作简报', chapter_count: 50,
      setup_draft: { world_rules: { rule: '规则' } } },
  })
  await renderPage('/projects/new?draft=draft-id')
  expect(await screen.findByDisplayValue('我的草稿')).toBeTruthy()
  expect(screen.getByDisplayValue('尚未写完的创作简报')).toBeTruthy()
  expect(screen.queryByRole('button', { name: /暂不规划/ })).toBeNull()
  expect((screen.getByRole('button', { name: '作品草稿已保存', hidden: true }) as HTMLButtonElement).disabled).toBe(true)
  expect(api.createProject).not.toHaveBeenCalled()
})

it('clears the restored draft when the same component navigates to a fresh form', async () => {
  vi.mocked(api.getCreation).mockResolvedValue({
    project: { id: 'draft-a', title: 'A 书名', genre: '悬疑', current_chapter: 0,
      target_words: 3000, creation_status: 'draft' },
    context: { premise: 'A 简报', chapter_count: 50,
      setup_draft: { world_rules: { rule: 'A 规则' } } },
  })
  await renderPage('/projects/new?draft=draft-a')
  expect(await screen.findByDisplayValue('A 书名')).toBeTruthy()
  expect(screen.getByRole('heading', { name: '② 设定骨架草稿' })).toBeTruthy()

  // This test intentionally discards the restored draft.
  const discard = vi.spyOn(window, 'confirm').mockReturnValue(true)
  await fireEvent.click(screen.getByRole('button', { name: 'new-project' }))
  await waitFor(() => expect(discard).toHaveBeenCalledTimes(1))

  await waitFor(() => expect((screen.getByLabelText('书名') as HTMLInputElement).value).toBe(''))
  expect(screen.getByRole('heading', { name: '新建长篇' })).toBeTruthy()
  expect(screen.queryByRole('heading', { name: '② 设定骨架草稿' })).toBeNull()
  expect((screen.getByRole('button', { name: '创建作品' }) as HTMLButtonElement).disabled).toBe(false)
})

it('clears draft A and keeps the form locked when restoring draft B fails', async () => {
  vi.mocked(api.getCreation).mockImplementation(async (draftId: string) => {
    if (draftId === 'draft-b') throw new Error('B restore failed')
    return {
      project: { id: 'draft-a', title: 'A 书名', genre: '悬疑', current_chapter: 0,
        target_words: 3000, creation_status: 'draft' },
      context: { premise: 'A 简报', chapter_count: 50,
        setup_draft: { world_rules: { rule: 'A 规则' } } },
    }
  })
  await renderPage('/projects/new?draft=draft-a')
  expect(await screen.findByDisplayValue('A 书名')).toBeTruthy()

  vi.spyOn(window, 'confirm').mockReturnValue(true) // explicitly accept changing this draft identity
  await fireEvent.click(screen.getByRole('button', { name: 'draft-b' }))

  expect(await screen.findByText('恢复草稿失败，请刷新重试')).toBeTruthy()
  expect((screen.getByLabelText('书名') as HTMLInputElement).value).toBe('')
  expect(screen.queryByRole('heading', { name: '② 设定骨架草稿' })).toBeNull()
  expect((screen.getByRole('button', { name: '创建作品' }) as HTMLButtonElement).disabled).toBe(true)
  expect(api.getCreation).toHaveBeenNthCalledWith(1, 'draft-a')
  expect(api.getCreation).toHaveBeenNthCalledWith(2, 'draft-b')
})

it('does not let a late draft A response overwrite restored draft B', async () => {
  let resolveA!: (value: Awaited<ReturnType<typeof api.getCreation>>) => void
  vi.mocked(api.getCreation).mockImplementation((draftId: string) => {
    if (draftId === 'draft-a') return new Promise((resolve) => { resolveA = resolve })
    return Promise.resolve({
      project: { id: 'draft-b', title: 'B 书名', genre: '悬疑', current_chapter: 0,
        target_words: 3000, creation_status: 'draft' },
      context: { premise: 'B 简报', chapter_count: 80, setup_draft: {} },
    })
  })
  await renderPage('/projects/new?draft=draft-a')
  await waitFor(() => expect(api.getCreation).toHaveBeenCalledWith('draft-a'))

  vi.spyOn(window, 'confirm').mockReturnValue(true) // explicitly accept changing this draft identity
  await fireEvent.click(screen.getByRole('button', { name: 'draft-b' }))
  expect(await screen.findByDisplayValue('B 书名')).toBeTruthy()
  await act(async () => resolveA({
    project: { id: 'draft-a', title: 'A 书名', genre: '悬疑', current_chapter: 0,
      target_words: 3000, creation_status: 'draft' },
    context: { premise: 'A 简报', chapter_count: 50, setup_draft: {} },
  }))

  expect((screen.getByLabelText('书名') as HTMLInputElement).value).toBe('B 书名')
  expect((screen.getByLabelText('创作简报') as HTMLTextAreaElement).value).toBe('B 简报')
})

it('keeps creation locked until both proposals finish and never claims degraded generation succeeded', async () => {
  let finishOutline!: (value: OutlineDraft) => void
  vi.mocked(api.createProject).mockResolvedValue({ id: 'new-id', title: '书', genre: '悬疑', current_chapter: 0, target_words: 3000, creation_status: 'draft' })
  vi.mocked(api.setupDraft).mockResolvedValue({ draft: {}, error: '模型不可用' })
  vi.mocked(api.outlineDraft).mockReturnValue(new Promise((resolve) => { finishOutline = resolve }))
  await renderPage()
  await fireEvent.input(screen.getByLabelText('创作简报'), { target: { value: '寻找真相' } })
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))
  await waitFor(() => expect(api.outlineDraft).toHaveBeenCalledTimes(1))
  expect((screen.getByRole('button', { name: /作品草稿已保存/ }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: /重新生成草稿/, hidden: true }) as HTMLButtonElement).disabled).toBe(true)
  finishOutline({ outline: { objective: '', volumes: [] }, error: '模型不可用' })
  expect(await screen.findByText(/草稿生成未全部完成/)).toBeTruthy()
  expect(screen.queryByText('作品已创建，设定与整书大纲草稿已生成，可编辑后确认')).toBeNull()
  expect(vi.mocked(api.createProject).mock.calls[0][0].request_id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  )
  expect(sessionStorage.getItem('myink.pending-project-creation')).toBeNull()
})

it('reuses one persisted request id when the first create attempt is retried', async () => {
  vi.stubGlobal('crypto', { randomUUID: vi.fn(() => '11111111-1111-4111-8111-111111111111') })
  vi.mocked(api.createProject).mockRejectedValue(new Error('temporary failure'))
  await renderPage()
  await fillCreationBrief()

  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))
  expect(await screen.findByText('创建作品失败，请重试')).toBeTruthy()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))
  await waitFor(() => expect(api.createProject).toHaveBeenCalledTimes(2))

  expect(vi.mocked(api.createProject).mock.calls.map(([body]) => body.request_id)).toEqual([
    '11111111-1111-4111-8111-111111111111',
    '11111111-1111-4111-8111-111111111111',
  ])
  expect(sessionStorage.getItem('myink.pending-project-creation')).toBe(
    '11111111-1111-4111-8111-111111111111',
  )
})

it('reuses the persisted request id after the page remounts', async () => {
  vi.stubGlobal('crypto', { randomUUID: vi.fn(() => '22222222-2222-4222-8222-222222222222') })
  vi.mocked(api.createProject).mockRejectedValue(new Error('temporary failure'))
  const first = await renderPage()
  await fillCreationBrief()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))
  expect(await screen.findByText('创建作品失败，请重试')).toBeTruthy()

  first.unmount()
  await renderPage()
  await fillCreationBrief()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))
  await waitFor(() => expect(api.createProject).toHaveBeenCalledTimes(2))

  expect(vi.mocked(api.createProject).mock.calls.map(([body]) => body.request_id)).toEqual([
    '22222222-2222-4222-8222-222222222222',
    '22222222-2222-4222-8222-222222222222',
  ])
})

it.each(['getItem', 'setItem'] as const)(
  'does not create without a safely persisted request id when sessionStorage.%s fails',
  async (method) => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => '33333333-3333-4333-8333-333333333333') })
    vi.spyOn(Storage.prototype, method).mockImplementation(() => {
      throw new DOMException('storage unavailable')
    })
    await renderPage()
    await fillCreationBrief()
    await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))

    expect(await screen.findByText('无法安全保存创建请求，请检查浏览器存储权限后重试')).toBeTruthy()
    expect(api.createProject).not.toHaveBeenCalled()
  },
)

function shortBookDraft(
  context: ProjectCreation['context'],
  creation_status: ProjectCreation['project']['creation_status'] = 'setup_confirmed',
): ProjectCreation {
  return {
    project: { id: 'short-id', title: '渡口', genre: '悬疑', current_chapter: 0,
      target_words: 3000, creation_status, form: 'short' as const },
    context: { premise: '最后一班船', form: 'short' as const, chapter_count: 2,
      chars_per_chapter: 2000, ...context },
  }
}

it('starts in the short form straight from its own section route, with no form switch to make', async () => {
  vi.mocked(api.createProject).mockResolvedValue({
    id: 'short-id', title: '渡口', genre: '悬疑', current_chapter: 0,
    target_words: 3000, creation_status: 'draft', form: 'short',
  })
  vi.mocked(api.setupDraft).mockResolvedValue({ draft: {}, error: null })
  vi.mocked(api.outlineDraft).mockResolvedValue({ outline: { objective: '', volumes: [] }, error: null })
  vi.mocked(api.getCreation).mockResolvedValue(shortBookDraft({}))
  await renderPage('/short/new')

  // 形态由入口决定，第 1 步不再有形态开关。
  expect(screen.queryByRole('button', { name: '短篇' })).toBeNull()
  expect(screen.queryByRole('button', { name: '长篇' })).toBeNull()
  const chapters = await screen.findByLabelText('章数（1–10）')
  // 章数初值要落在短篇区间里——长篇的 200 会被后端章数校验挡下。
  expect((chapters as HTMLInputElement).value).toBe('5')

  await fireEvent.input(chapters, { target: { value: '4' } })
  await fireEvent.input(screen.getByLabelText('每章字数（1000–8000）'), { target: { value: '3000' } })
  await fillCreationBrief()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))

  await waitFor(() => expect(api.createProject).toHaveBeenCalledTimes(1))
  expect(vi.mocked(api.createProject).mock.calls[0][0]).toMatchObject({
    form: 'short', chapter_count: 4, chars_per_chapter: 3000,
  })
})

it('edits and confirms the short plan chapter by chapter', async () => {
  vi.mocked(api.getCreation).mockResolvedValue(shortBookDraft({
    outline_draft: {
      objective: '让青溪渡停航',
      volumes: [{
        volume_seq: 1, title: '全篇 · 渡口', theme: '离开', goal: '查清父亲死因',
        chapter_start: 1, chapter_end: 2,
        chapters: [
          { chapter_seq: 1, title: '末班船', goal: '上船', key_scene: '码头夜雨',
            character_action: '登船', escalation_or_payoff: '船票是假的', hook: '船开了' },
          { chapter_seq: 2, title: '对岸', goal: '下船', key_scene: '雾中渡口',
            character_action: '下船', escalation_or_payoff: '真相揭开', hook: '回到起点' },
        ],
      }],
    },
  }))
  vi.mocked(api.confirmOutline).mockResolvedValue({ outline: null })
  await renderPage('/projects/new?draft=short-id')

  expect(await screen.findByDisplayValue('末班船')).toBeTruthy()
  expect(screen.getByDisplayValue('码头夜雨')).toBeTruthy()
  // 卷 + 阶段那套是长篇的形状，短篇的写手读的是逐章细纲。
  expect(screen.queryByText('+ 本卷加一段')).toBeNull()

  await fireEvent.input(screen.getByLabelText('第 2 章 · 本章目标'), { target: { value: '下船离开' } })
  await fireEvent.click(screen.getByRole('button', { name: '选择资源并完成建书' }))
  await fireEvent.click(screen.getByRole('button', { name: '确认资源并创建作品' }))

  await waitFor(() => expect(api.confirmOutline).toHaveBeenCalledTimes(1))
  const body = vi.mocked(api.confirmOutline).mock.calls[0][1]
  expect(body.chapter_count).toBe(2)
  expect(body.volumes[0].chapters).toEqual([
    expect.objectContaining({ chapter_seq: 1, title: '末班船', goal: '上船' }),
    expect.objectContaining({ chapter_seq: 2, goal: '下船离开', hook: '回到起点' }),
  ])
})

it('tells the user when the short plan was compressed or flagged by the plan review', async () => {
  vi.mocked(api.getCreation).mockResolvedValue(shortBookDraft({
    chapter_count: 10, chars_per_chapter: 2000, lengths_compressed: true,
    outline_warning: '两版方案都被审纲建议改稿（第 3 章没有回报落地）；已保留第一版方案',
  }))
  await renderPage('/projects/new?draft=short-id')

  expect(await screen.findByText(/每章字数已按全篇 20000 字上限归一为每章 2000 字/)).toBeTruthy()
  expect(screen.getByText(/两版方案都被审纲建议改稿/)).toBeTruthy()
})

it('keeps the long-form chapter range and declares the long form explicitly', async () => {
  vi.mocked(api.createProject).mockResolvedValue({
    id: 'long-id', title: '破晓录', genre: '悬疑', current_chapter: 0,
    target_words: 3000, creation_status: 'draft',
  })
  vi.mocked(api.setupDraft).mockResolvedValue({ draft: {}, error: null })
  vi.mocked(api.outlineDraft).mockResolvedValue({ outline: { objective: '', volumes: [] }, error: null })
  await renderPage('/long/new')

  expect(screen.queryByLabelText('章数（1–10）')).toBeNull()
  expect(screen.queryByLabelText('每章字数（1000–8000）')).toBeNull()
  expect(screen.getByLabelText('每章目标字数（500–20000）')).toBeTruthy()

  await fillCreationBrief()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))

  await waitFor(() => expect(api.createProject).toHaveBeenCalledTimes(1))
  const body = vi.mocked(api.createProject).mock.calls[0][0]
  // 形态显式声明：分区入口选错时后端能立刻挡下，而不是悄悄建出另一形态的书。
  expect(body).toMatchObject({ form: 'long', chapter_count: 200 })
  expect(body).not.toHaveProperty('chars_per_chapter')
  expect(vi.mocked(api.outlineDraft).mock.calls[0][1]).not.toHaveProperty('chars_per_chapter')
})

// ---- 建书第①步选文风（值直接交给后端 resolve_style_selection）----


const STYLE_ITEMS = [
  { id: 'wr:platform', origin: 'platform' as const, resource_id: 'platform-id', name: '九州问天', builtin: true, removable: false,
    profile: {}, note: '', sample_chars: 0, created_at: null },
  { id: 'wr:personal', origin: 'personal' as const, resource_id: 'personal-id', name: '渡口白描', builtin: false, removable: true,
    profile: {}, note: '', sample_chars: 10, created_at: '2026-09-24' },
]

function stubLongCreation() {
  vi.mocked(api.createProject).mockResolvedValue({
    id: 'long-id', title: '破晓录', genre: '悬疑', current_chapter: 0,
    target_words: 3000, creation_status: 'draft',
  })
  vi.mocked(api.setupDraft).mockResolvedValue({ draft: {}, error: null })
  vi.mocked(api.outlineDraft).mockResolvedValue({ outline: { objective: '', volumes: [] }, error: null })
}

it('lists the builtin style before mine, each marked with where it comes from', async () => {
  vi.mocked(styleLibraryApi.resources).mockResolvedValue({ items: STYLE_ITEMS })
  await renderPage('/long/new')

  const select = await screen.findByLabelText('文风')
  // 选项由 useEffect 里的异步 list() 填，而 select 首帧就在，所以这里必须重试断言。
  await waitFor(() =>
    expect(Array.from(select.querySelectorAll('option')).map((o) => o.textContent)).toEqual([
      '不指定', '九州问天（平台）', '渡口白描（我的）',
    ]),
  )
})

it('defaults to no style and sends null', async () => {
  vi.mocked(styleLibraryApi.resources).mockResolvedValue({ items: STYLE_ITEMS })
  stubLongCreation()
  await renderPage('/long/new')
  await screen.findByLabelText('文风')

  await fillCreationBrief()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))

  await waitFor(() => expect(api.createProject).toHaveBeenCalledTimes(1))
  expect(vi.mocked(api.createProject).mock.calls[0][0].style_item_id).toBeNull()
})

it('submits the selected style item id with the project', async () => {
  vi.mocked(styleLibraryApi.resources).mockResolvedValue({ items: STYLE_ITEMS })
  stubLongCreation()
  await renderPage('/long/new')

  await fireEvent.change(await screen.findByLabelText('文风'), { target: { value: 'wr:personal' } })
  await fillCreationBrief()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))

  await waitFor(() => expect(api.createProject).toHaveBeenCalledTimes(1))
  expect(vi.mocked(api.createProject).mock.calls[0][0].style_item_id).toBe('wr:personal')
})

// ---- 建书第②步：设定骨架因题材而异（§7.11，等级阶梯不是通用维度）----

const GENRE_CHIPS = [
  { ...emptyFields(), id: 'xiuxian', name: '修仙', group: '玄幻修仙',
    setup_caps: { power_scaling: true, numerical_system: true, era_research: false } },
  { ...emptyFields(), id: 'dushi-richang', name: '都市日常', group: '都市现代',
    setup_caps: { power_scaling: false, numerical_system: false, era_research: false } },
]

async function createWithGenre(genreName: string) {
  vi.mocked(api.listGenrePacks).mockResolvedValue(GENRE_CHIPS)
  stubLongCreation()
  await renderPage('/long/new')
  // 题材名在主题材与辅题材两处都出现，取主题材那一档（DOM 里先渲染的就是它）
  const [primaryChip] = await screen.findAllByRole('button', { name: genreName })
  await fireEvent.click(primaryChip)
  await fillCreationBrief()
  await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))
  await screen.findByText('世界观规则（每行「键：值」）')
}

it('offers the realm ladder only for genres that have one', async () => {
  await createWithGenre('修仙')
  expect(screen.getByText('境界体系（每行一阶）')).toBeTruthy()
})

it('drops the realm ladder for genres without power scaling', async () => {
  await createWithGenre('都市日常')
  expect(screen.queryByText('境界体系（每行一阶）')).toBeNull()
  // 通用骨架照旧：题材只决定有没有等级阶梯，不是把整块设定省掉
  expect(screen.getByText('世界观规则（每行「键：值」）')).toBeTruthy()
  expect(screen.getByText('核心人物')).toBeTruthy()
  expect(screen.queryByPlaceholderText('境界上限')).toBeNull()
})

it('offers published genre selection without editable root fields', async () => {
 vi.mocked(api.listGenrePacks).mockResolvedValue([{...emptyFields(),id:'fantasy',name:'奇幻',group:'幻想',selling_point:'平台发布卖点'}])
 await renderPage('/projects/new')
 await screen.findAllByRole('button',{name:'奇幻'})
 expect(screen.queryByLabelText('核心卖点')).toBeNull()
 await fireEvent.click(screen.getAllByRole('button',{name:'奇幻'})[0])
 fillCreationBrief()
 await fireEvent.click(screen.getByRole('button',{name:'创建作品'}))
 await waitFor(() => expect(api.createProject).toHaveBeenCalled())
 expect(vi.mocked(api.createProject).mock.lastCall?.[0]).not.toHaveProperty('genre_fields')
})

it('preserves partial world rule keys and empty newlines during setup editing', async () => {
  vi.mocked(api.getCreation).mockResolvedValue({
    project: { id: 'draft-id', title: '草稿', genre: '悬疑', current_chapter: 0,
      target_words: 3000, creation_status: 'draft' },
    context: { premise: '故事', chapter_count: 50, setup_draft: { world_rules: {} } },
  })
  await renderPage('/projects/new?draft=draft-id')
  const label = await screen.findByText('世界观规则（每行「键：值」）')
  const box = label.parentElement!.querySelector('textarea')!
  await fireEvent.input(box, { target: { value: '魔' } })
  expect(box.value).toBe('魔')
  await fireEvent.input(box, { target: { value: box.value + '法：有代价\n' } })
  expect(box.value).toBe('魔法：有代价\n')
  await fireEvent.input(box, { target: { value: box.value + '时间：不可逆' } })
  expect(box.value).toBe('魔法：有代价\n时间：不可逆')
})


it('does not let a late create response replace a newly selected draft', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.createProject>>) => void
  vi.mocked(api.createProject).mockReturnValue(new Promise(resolve => { finish = resolve }))
  vi.mocked(api.getCreation).mockResolvedValue({ project: { id: 'draft-b', title: '新草稿 B', genre: '悬疑', current_chapter: 0, target_words: 3000, creation_status: 'draft' }, context: { premise: 'B 简报', chapter_count: 50, setup_draft: {} } })
  await renderPage()
  await fillCreationBrief(); await fireEvent.click(screen.getByRole('button', { name: '创建作品' }))
  vi.spyOn(window, 'confirm').mockReturnValue(true) // explicitly accept changing this draft identity
  await fireEvent.click(screen.getByRole('button', { name: 'draft-b' }))
  await screen.findByDisplayValue('新草稿 B')
  finish({ id: 'old-create', title: '旧创建', genre: '', current_chapter: 0, target_words: 3000, creation_status: 'draft' })
  await new Promise(resolve => setTimeout(resolve, 0))
  expect((screen.getByLabelText('书名') as HTMLInputElement).value).toBe('新草稿 B')
  expect(api.setupDraft).not.toHaveBeenCalled()
})

it('ignores setup generation that completes after selecting another draft', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.setupDraft>>) => void
  vi.mocked(api.getCreation).mockImplementation(async id => ({ project: { id, title: id, genre: '', current_chapter: 0, target_words: 3000, creation_status: 'draft' }, context: { premise: id, chapter_count: 50, setup_draft: { world_rules: { rule: id } } } }))
  vi.mocked(api.setupDraft).mockReturnValue(new Promise(resolve => { finish = resolve }))
  await renderPage('/projects/new?draft=draft-a')
  await fireEvent.click(await screen.findByRole('button', { name: '重新生成草稿' }))
  vi.spyOn(window, 'confirm').mockReturnValue(true) // explicitly accept changing this draft identity
  await fireEvent.click(screen.getByRole('button', { name: 'draft-b' }))
  await waitFor(() => expect((screen.getByLabelText('书名') as HTMLInputElement).value).toBe('draft-b'))
  finish({ draft: { world_rules: { secret: '迟到的 A 内容' } }, error: null })
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(screen.queryByDisplayValue('secret：迟到的 A 内容')).toBeNull()
  expect(screen.getByDisplayValue('rule：draft-b')).toBeTruthy()
})

it('does not apply a pending creation or launch proposals after logout', async () => {
 let finish!:(value:Awaited<ReturnType<typeof api.createProject>>)=>void
 vi.mocked(api.createProject).mockReturnValue(new Promise(resolve=>{finish=resolve}))
 await renderPage(); await fillCreationBrief(); await fireEvent.click(screen.getByRole('button',{name:'创建作品'}))
 creationStatus.value='anonymous'
 await new Promise(resolve=>setTimeout(resolve,0))
 finish({id:'late-private',title:'旧书',genre:'',current_chapter:0,target_words:3000,creation_status:'draft'})
 await new Promise(resolve=>setTimeout(resolve,0))
 expect(api.setupDraft).not.toHaveBeenCalled()
 expect(screen.queryByRole('heading',{name:'② 设定骨架草稿'})).toBeNull()
})

it('keeps a creation brief on cancelled navigation and native unload, including same-page draft changes', async () => {
  const { router } = await renderPage('/long/new')
  await fillCreationBrief()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await router.push('/long/new?draft=other')
  expect(router.currentRoute.value.fullPath).toBe('/long/new')
  expect((screen.getByLabelText('创作简报') as HTMLTextAreaElement).value).toBe('寻找真相')
  const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
  await router.push('/long'); expect(router.currentRoute.value.path).toBe('/long/new')
  expect(confirm).toHaveBeenCalledTimes(2)
  confirm.mockReturnValue(true); await router.push('/long'); expect(router.currentRoute.value.path).toBe('/long')
})

const longDraft = () => ({project:{id:'long-id',title:'长篇',form:'long',genre:'悬疑',current_chapter:0,target_words:3000,creation_status:'setup_confirmed'},context:{premise:'寻找真相',setup_draft:{world_rules:{rule:'规则'}},outline_draft:{objective:'查清真相',volumes:[{volume_seq:1,title:'第一卷',theme:'追寻',goal:'找到线索',chapter_start:1,chapter_end:20,stages:[]}]}}} as ProjectCreation)
it('requires the resources dialog and CAS selection before finishing a long book', async () => {
 vi.mocked(api.getCreation).mockResolvedValue(longDraft())
 vi.mocked(api.confirmSetup).mockResolvedValue({} as never)
 vi.mocked(api.confirmOutline).mockResolvedValue({outline:null})
 const {router}=await renderPage('/long/new?draft=long-id')
 await fireEvent.click(await screen.findByRole('button',{name:'选择资源并完成建书'}))
 expect(screen.getByRole('dialog', {name:'选择写作资源'})).toBeTruthy()
 expect(api.confirmOutline).not.toHaveBeenCalled()
 await fireEvent.click(screen.getByRole('button',{name:'确认资源并创建作品'}))
 await waitFor(()=>expect(router.currentRoute.value.path).toBe('/projects/long-id'))
 expect(writingResourcesApi.select).toHaveBeenCalledWith('long-id',4,[{origin:'platform',resource_id:'style-1'}])
 expect(vi.mocked(writingResourcesApi.select).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(api.confirmOutline).mock.invocationCallOrder[0])
 expect(router.options.history.state.beginShortWriting).toBeUndefined()
})
it('keeps the same draft and all content when resource selection fails or is cancelled', async () => {
 vi.mocked(api.getCreation).mockResolvedValue(longDraft())
 vi.mocked(writingResourcesApi.select).mockRejectedValueOnce(new Error('conflict'))
 const {router}=await renderPage('/long/new?draft=long-id')
 await fireEvent.click(await screen.findByRole('button',{name:'选择资源并完成建书'}))
 await fireEvent.click(screen.getByRole('button',{name:'确认资源并创建作品'}))
 expect(await screen.findByRole('alert')).toBeTruthy()
 expect(api.confirmOutline).not.toHaveBeenCalled()
 await fireEvent.click(screen.getByRole('button',{name:'取消资源选择'}))
 expect(router.currentRoute.value.fullPath).toBe('/long/new?draft=long-id')
 expect(screen.getByDisplayValue('查清真相')).toBeTruthy()
 expect(api.createProject).not.toHaveBeenCalled()
})
it('shows one long-book step, preserves edited setup when returning, and scrolls each step to top', async () => {
 vi.mocked(api.getCreation).mockResolvedValue({...longDraft(),project:{...longDraft().project,creation_status:'draft'}})
 vi.mocked(api.confirmSetup).mockResolvedValue({} as never)
 await renderPage('/long/new?draft=long-id')
 expect(await screen.findByRole('heading',{name:'② 设定骨架草稿'})).toBeTruthy()
 expect(screen.queryByRole('heading',{name:'① 作品信息'})).toBeNull()
 expect(screen.queryByRole('heading',{name:'③ 整书大纲'})).toBeNull()
 const field=screen.getByDisplayValue('rule：规则')
 await fireEvent.input(field,{target:{value:'rule：保留修改'}})
 const container=screen.getByRole('main').parentElement!
 container.scrollTop=500
 await fireEvent.click(screen.getByRole('button',{name:'确认设定，下一步'}))
 expect(await screen.findByRole('heading',{name:'③ 整书大纲'})).toBeTruthy()
 await waitFor(()=>expect(container.scrollTop).toBe(0))
 await fireEvent.click(screen.getByRole('button',{name:'上一步'}))
 expect(await screen.findByDisplayValue('rule：保留修改')).toBeTruthy()
})
it('keeps generation failures visible when reviewing another long-book step', async () => {
 vi.mocked(api.getCreation).mockResolvedValue({...longDraft(),context:{...longDraft().context,setup_error:'设定模型故障'}})
 await renderPage('/long/new?draft=long-id')
 expect(await screen.findByRole('heading',{name:'③ 整书大纲'})).toBeTruthy()
 expect(screen.getByRole('alert').textContent).toContain('设定模型故障')
})

it('keeps a visible wait while the created book is still generating its setup and outline', async () => {
 let failSetup!: (reason: Error) => void
 let failOutline!: (reason: Error) => void
 vi.mocked(api.createProject).mockResolvedValue({id:'draft-wait',title:'未命名作品',genre:'',current_chapter:0,target_words:3000,creation_status:'draft'})
 vi.mocked(api.setupDraft).mockReturnValue(new Promise((_resolve,reject)=>{failSetup=reject}))
 vi.mocked(api.outlineDraft).mockReturnValue(new Promise((_resolve,reject)=>{failOutline=reject}))
 await renderPage('/long/new')
 await fillCreationBrief()
 await fireEvent.click(screen.getByRole('button',{name:'创建作品'}))
 await screen.findByRole('button',{name:'作品草稿已保存'})
 expect(screen.getByRole('status').textContent).toContain('正在生成设定与整书大纲')
 expect(screen.getByRole('progressbar').hasAttribute('value')).toBe(false)
 expect((screen.getByLabelText('创作简报') as HTMLTextAreaElement).value).toBe('寻找真相')
 await act(()=>{failSetup(new Error('offline'));failOutline(new Error('offline'))})
 await waitFor(()=>expect(screen.queryByRole('progressbar')).toBeNull())
 expect(await screen.findByText(/草稿生成未全部完成/)).toBeTruthy()
})
