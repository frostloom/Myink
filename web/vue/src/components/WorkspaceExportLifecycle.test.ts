import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import WorkspacePage from '../pages/WorkspacePage.vue'
import { api } from '../../../src/lib/api'
vi.mock('../authContext', () => ({ useAuth: () => ({ session: ref({ userId: 'u' }), logout: vi.fn() }) }))
vi.mock('../composables/useTaskEvents', () => ({ useTaskEvents: () => ({ phase: 'idle', status: null, runs: [], nodes: [], artifacts: [], budget: null, progress: null, shortProgress: null, error: null, payload: {}, retry: vi.fn(), refresh: vi.fn() }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it.each(['resolve', 'reject'])('ignores old export %s while the new project export is pending', async outcome => {
  const download = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  vi.spyOn(api, 'listLessons').mockResolvedValue([])
  const books = ['a', 'b'].map(id => ({ id, title: id, genre: 'g', current_chapter: 2, target_words: 2000, creation_status: 'ready' as const, form: 'long' as const }))
  const chapters = [1, 2].map(n => ({ id: `a${n}`, chapter_seq: n, title: `A${n}`, summary: null, status: 'confirmed' as const, word_count: 20 }))
  vi.spyOn(api, 'listProjects').mockResolvedValue(books)
  vi.spyOn(api, 'listChapters').mockImplementation(async id => id === 'a' ? chapters : chapters.map(c=>({...c,id:c.id.replace('a','b')})))
  vi.spyOn(api, 'listCandidates').mockResolvedValue([])
  vi.spyOn(api, 'listGraph').mockResolvedValue({ nodes: [], edges: [] })
  vi.spyOn(api, 'listForeshadows').mockResolvedValue([])
  vi.spyOn(api, 'listTasks').mockResolvedValue([])
  let finish!: (value: Awaited<ReturnType<typeof api.getChapter>>) => void
  let fail!: (reason:Error) => void
  const get = vi.spyOn(api, 'getChapter').mockImplementationOnce(() => new Promise((resolve,reject) => { finish = resolve; fail = reject })).mockImplementation(()=>new Promise(()=>{}))
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId', component: WorkspacePage }] })
  await router.push('/projects/a'); await router.isReady()
  render(RouterView, { global: { plugins: [router], stubs: Object.fromEntries(['ResourceUpdates', 'AuditPanel', 'CandidatePanel', 'ChapterEditor', 'ChapterPlanPanel', 'ChapterList', 'GenerationPanel', 'LessonsPanel', 'ProjectRail', 'RingProgress', 'TaskTimeline', 'StreamingChapterView'].map(name => [name, true])) } })
  await flushPromises()
  await fireEvent.click(screen.getByRole('button', { name: '导出 .md' }))
  expect(get).toHaveBeenCalledWith('a', 'a1')
  await router.push('/projects/b'); await flushPromises()
  await fireEvent.click(screen.getByRole('button', { name: '导出 .md' }))
  expect(get).toHaveBeenCalledWith('b','b1')
  if(outcome==='resolve') finish({ ...chapters[0], content: 'A1', version: 1 }); else fail(new Error('old export offline'))
  await flushPromises()
  expect(get).not.toHaveBeenCalledWith('a','a2')
  expect(download).not.toHaveBeenCalled()
  expect(screen.queryByText('导出失败')).toBeNull()
  expect((screen.getByRole('button',{name:'导出中…'}) as HTMLButtonElement).disabled).toBe(true)
})
