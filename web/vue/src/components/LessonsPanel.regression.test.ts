import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { api } from '../../../src/lib/api'
import type { WritingLesson } from '../../../src/types'
import LessonsPanel from './LessonsPanel.vue'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const lesson = (id: string): WritingLesson => ({ lesson_id: id, content: `经验${id}`, status: 'proposed', category: 'style', lesson_type: 'avoid', evidence: [], confidence: 1, source_chapter: 1, recurrence_count: 0, last_recurrence_at: null, created_at: null })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('clears the previous project before the next lesson list arrives', async () => {
  const next = deferred<WritingLesson[]>()
  vi.spyOn(api, 'listLessons').mockResolvedValueOnce([lesson('A')]).mockReturnValueOnce(next.promise)
  const view = render(LessonsPanel, { props: { projectId: 'A' } })
  await flushPromises()
  await fireEvent.click(screen.getByRole('button', { name: /写作经验/ }))
  expect(screen.getByText('经验A')).toBeTruthy()
  await view.rerender({ projectId: 'B' })
  expect(screen.queryByText('经验A')).toBeNull()
  next.resolve([lesson('B')]); await flushPromises()
  expect(screen.getByText('经验B')).toBeTruthy()
})

it('ignores a late action refresh after switching projects', async () => {
  const oldRefresh = deferred<WritingLesson[]>()
  vi.spyOn(api, 'listLessons').mockResolvedValueOnce([lesson('A')]).mockReturnValueOnce(oldRefresh.promise).mockResolvedValueOnce([lesson('B')])
  vi.spyOn(api, 'confirmLesson').mockResolvedValue({ lesson_id: 'A', status: 'active' })
  const view = render(LessonsPanel, { props: { projectId: 'A' } })
  await flushPromises(); await fireEvent.click(screen.getByRole('button', { name: /写作经验/ }))
  await fireEvent.click(screen.getByRole('button', { name: '确认生效' })); await flushPromises()
  await view.rerender({ projectId: 'B' }); await flushPromises()
  oldRefresh.resolve([lesson('A')]); await flushPromises()
  expect(screen.getByText('经验B')).toBeTruthy()
  expect(screen.queryByText('经验A')).toBeNull()
  expect((screen.getByRole('button', { name: '确认生效' }) as HTMLButtonElement).disabled).toBe(false)
})

it('ignores a stale action error and does not unlock the next project action', async () => {
  const oldAction = deferred<{ lesson_id: string; status: 'active' }>()
  const nextAction = deferred<{ lesson_id: string; status: 'active' }>()
  vi.spyOn(api, 'listLessons').mockImplementation(async id => [lesson(id)])
  vi.spyOn(api, 'confirmLesson').mockReturnValueOnce(oldAction.promise).mockReturnValueOnce(nextAction.promise)
  const view = render(LessonsPanel, { props: { projectId: 'A' } })
  await flushPromises(); await fireEvent.click(screen.getByRole('button', { name: /写作经验/ }))
  await fireEvent.click(screen.getByRole('button', { name: '确认生效' }))
  await view.rerender({ projectId: 'B' }); await flushPromises()
  expect((screen.getByRole('button', { name: '确认生效' }) as HTMLButtonElement).disabled).toBe(false)
  await fireEvent.click(screen.getByRole('button', { name: '确认生效' }))
  oldAction.reject(new Error('old project error')); await flushPromises()
  expect(screen.queryByText(/old project error/)).toBeNull()
  expect((screen.getByRole('button', { name: '处理中…' }) as HTMLButtonElement).disabled).toBe(true)
  nextAction.resolve({ lesson_id: 'B', status: 'active' }); await flushPromises()
})
