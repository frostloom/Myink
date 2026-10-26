// @vitest-environment jsdom
// 设定页台账两块（批次 2）：事件台账（§7.4）渲染摘要与人名；人物状态变化时间线（§7.7）
// 首次展开才懒加载、且**已失效行也在**（这正是新增接口存在的理由，压平后看不到）。
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it, vi } from 'vitest'
import LorePage from './LorePage.vue'
import { api } from '../../../src/lib/api'
import type { CharacterCard, StoryEvent, CharacterStateChange } from '../../../src/types'

vi.mock('../components/ProjectRail.vue', () => ({ default: {template:'<nav>项目</nav>'} }))
vi.mock('../components/WorldGraph.vue', () => ({ default: {template:'<div>图谱</div>'} }))
vi.mock('../authContext', () => ({ useAuth: () => ({ logout: vi.fn() }) }))
vi.mock('../../../src/lib/api', () => ({
  ApiError: class ApiError extends Error { code = 'API_ERROR' },
  api: {
    listProjects: vi.fn(), getWorld: vi.fn(), getCharacters: vi.fn(),
    listEntities: vi.fn(), listForeshadows: vi.fn(), listChapters: vi.fn(),
    getOutline: vi.fn(), listEvents: vi.fn(), getCharacterStateHistory: vi.fn(),
  },
}))

// 卡片名与事件参与人取不同人名，避免 getByText 命中两处
const CARD: CharacterCard = {
  id: 'c1', name: '顾长歌', race: '人族', origin: null, realm_cap: '金丹',
  personality: null, base_attrs: {}, state: { realm: '金丹初期' },
}

const EVENTS: StoryEvent[] = [
  { id: 'e2', summary: '沈岳夜访秘境', participants: ['沈岳'],
    source_chapter: 7, confidence: 0.8 },
  { id: 'e1', summary: '林晚于青云山夺剑', participants: ['林晚'],
    source_chapter: 3, confidence: 0.9 },
]

const HISTORY: CharacterStateChange[] = [
  { field: 'realm', old_value: '练气九层', new_value: '筑基一层', chapter_seq: 2,
    source_chapter: 2, confidence: 0.9, valid_from: 2, valid_to: null },
  // 已失效行（valid_to 非空）：get_character_state 会把它丢掉，端点与 UI 都不能丢
  { field: 'realm', old_value: '筑基一层', new_value: '筑基三层', chapter_seq: 3,
    source_chapter: 3, confidence: 0.8, valid_from: 3, valid_to: 5 },
  { field: 'realm', old_value: '筑基三层', new_value: '金丹初期', chapter_seq: 5,
    source_chapter: 5, confidence: 0.95, valid_from: 5, valid_to: null },
]

function seedPage() {
  vi.mocked(api.listProjects).mockResolvedValue([])
  vi.mocked(api.getWorld).mockResolvedValue({
    world_rules: {}, hard_constraints: [], factions: [], locations: [],
  })
  vi.mocked(api.getCharacters).mockResolvedValue([CARD])
  vi.mocked(api.listEntities).mockResolvedValue([])
  vi.mocked(api.listForeshadows).mockResolvedValue([])
  vi.mocked(api.listChapters).mockResolvedValue([])
  vi.mocked(api.getOutline).mockResolvedValue({ outline: null })
  vi.mocked(api.listEvents).mockResolvedValue([])
  vi.mocked(api.getCharacterStateHistory).mockResolvedValue([])
}

async function renderPage() {const router=createRouter({history:createMemoryHistory(),routes:[{path:'/projects/:projectId/lore',component:{template:'<div/>'}}]});await router.push('/projects/p/lore');return render(LorePage,{global:{plugins:[router]}})}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('renders the event ledger with summaries and participant names', async () => {
  seedPage()
  vi.mocked(api.listEvents).mockResolvedValue(EVENTS)

  await renderPage()

  // 「事件台账」标题不依赖数据、首帧就在，拿它当门等于没等——要等就等数据本身。
  expect(await screen.findByText('林晚于青云山夺剑')).toBeTruthy()
  expect(screen.getByText('事件台账')).toBeTruthy()
  expect(screen.getByText('林晚')).toBeTruthy()
  expect(screen.getByText('沈岳')).toBeTruthy()
})

it('loads the state-change timeline on first expand, invalidated rows included', async () => {
  seedPage()
  vi.mocked(api.getCharacterStateHistory).mockResolvedValue(HISTORY)

  await renderPage()

  // 未展开不拉数据（一次打 N 个请求不值当）
  expect(api.getCharacterStateHistory).not.toHaveBeenCalled()

  await fireEvent.click(await screen.findByRole('button', { name: /顾长歌/ }))

  expect(await screen.findByText('练气九层 → 筑基一层')).toBeTruthy()
  expect(screen.getByText('筑基一层 → 筑基三层')).toBeTruthy()
  expect(screen.getByText('筑基三层 → 金丹初期')).toBeTruthy()
  expect(vi.mocked(api.getCharacterStateHistory).mock.calls).toEqual([['p', 'c1']])

  // 收起再展开不重复拉（loaded 兼作只拉一次闸）
  await fireEvent.click(screen.getByRole('button', { name: /顾长歌/ }))
  await fireEvent.click(screen.getByRole('button', { name: /顾长歌/ }))
  await screen.findByText('练气九层 → 筑基一层')
  expect(vi.mocked(api.getCharacterStateHistory).mock.calls).toEqual([['p', 'c1']])
})
it('keeps outline folds, chapter memory, entity groups, foreshadows and world rules',async()=>{
 seedPage()
 vi.mocked(api.getOutline).mockResolvedValue({outline:{objective:'终局目标',volumes:[{volume_seq:1,title:'起航',chapter_start:1,chapter_end:10,theme:'成长',goal:'卷目标',key_results:['KR目标'],end_event:'卷末相遇',stages:[{name:'初识',goal:'阶段目标',chapter_start:1,chapter_end:3}]}]}} as never)
 vi.mocked(api.getWorld).mockResolvedValue({world_rules:{realm_order:['练气','筑基'],magic:'规则内容'},hard_constraints:['不能复活'],factions:[{name:'青云宗',stance:'中立',resources:['灵石']}],locations:[{name:'青云山'}]})
 vi.mocked(api.listEntities).mockResolvedValue([{id:'i',name:'灵剑',entity_type:'item',description:'古剑',first_seen_chapter:1}] as never)
 vi.mocked(api.listForeshadows).mockResolvedValue([{id:'f',status:'resolved',planted_chapter:1,resolved_chapter:5,description:'剑的来历'}] as never)
 vi.mocked(api.listChapters).mockResolvedValue([{id:'ch',chapter_seq:1,status:'completed',word_count:3000,summary:'章节摘要'}] as never)
 await renderPage();expect(await screen.findByText('终局目标')).toBeTruthy();expect(screen.getByText('起航',{exact:false})).toBeTruthy();expect(screen.getByText('章节摘要')).toBeTruthy();expect(screen.getByText('灵剑')).toBeTruthy();expect(screen.getByText('剑的来历')).toBeTruthy();expect(screen.getByText('规则内容')).toBeTruthy();expect(screen.getByText('不能复活')).toBeTruthy();expect(screen.getByText('青云宗')).toBeTruthy()
})
