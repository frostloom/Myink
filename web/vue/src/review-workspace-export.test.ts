import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import WorkspacePage from './pages/WorkspacePage.vue'
import { api } from '../../src/lib/api'
vi.mock('./authContext', () => ({ useAuth: () => ({ session: ref({ userId: 'u' }), logout: vi.fn() }) }))
vi.mock('./composables/useTaskEvents', () => ({ useTaskEvents: () => ({ phase: 'idle', status: null, runs: [], nodes: [], artifacts: [], budget: null, progress: null, shortProgress: null, error: null, payload: {}, retry: vi.fn(), refresh: vi.fn() }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('pins an in-flight markdown export to its original project', async () => {
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  vi.spyOn(api, 'listLessons').mockResolvedValue([])
  const books = ['a', 'b'].map(id => ({ id, title: id, genre: 'g', current_chapter: 2, target_words: 2000, creation_status: 'ready' as const, form: 'long' as const }))
  const chapters = [1, 2].map(n => ({ id: `a${n}`, chapter_seq: n, title: `A${n}`, summary: null, status: 'confirmed' as const, word_count: 20 }))
  vi.spyOn(api, 'listProjects').mockResolvedValue(books)
  vi.spyOn(api, 'listChapters').mockImplementation(async id => id === 'a' ? chapters : [])
  vi.spyOn(api, 'listCandidates').mockResolvedValue([])
  vi.spyOn(api, 'listGraph').mockResolvedValue({ nodes: [], edges: [] })
  vi.spyOn(api, 'listForeshadows').mockResolvedValue([])
  vi.spyOn(api, 'listTasks').mockResolvedValue([])
  let finish!: (value: Awaited<ReturnType<typeof api.getChapter>>) => void
  const get = vi.spyOn(api, 'getChapter').mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValue({ ...chapters[1], content: 'A2', version: 1 })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId', component: WorkspacePage }] })
  await router.push('/projects/a'); await router.isReady()
  render(RouterView, { global: { plugins: [router], stubs: Object.fromEntries(['ResourceUpdates', 'AuditPanel', 'CandidatePanel', 'ChapterEditor', 'ChapterPlanPanel', 'ChapterList', 'GenerationPanel', 'LessonsPanel', 'ProjectRail', 'RingProgress', 'TaskTimeline', 'StreamingChapterView'].map(name => [name, true])) } })
  await flushPromises()
  await fireEvent.click(screen.getByRole('button', { name: '导出 .md' }))
  expect(get).toHaveBeenCalledWith('a', 'a1')
  await router.push('/projects/b'); await flushPromises()
  finish({ ...chapters[0], content: 'A1', version: 1 }); await flushPromises()
  expect(get).not.toHaveBeenCalledWith('b', 'a2')
})
