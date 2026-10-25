// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from '../lib/api'
import type { ChapterMeta } from '../types'
import { GenerationPanel } from './GenerationPanel'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      generateChapter: vi.fn(),
      generateBatch: vi.fn(),
    },
  }
})

const chapter: ChapterMeta = {
  id: 'chapter-16',
  chapter_seq: 16,
  title: '第十六章',
  status: 'confirmed',
  word_count: 3000,
  summary: null,
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

it('shows the writing controls by default and starts the next chapter from a direct click', async () => {
  vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'task-17', trace_id: 'trace-17', status: 'queued' })
  const onTaskStart = vi.fn()

  render(
    <GenerationPanel
      projectId="project-1"
      chapters={[chapter]}
      selectedChapter={chapter}
      onTaskStart={onTaskStart}
    />,
  )

  const button = screen.getByRole('button', { name: '写下一章（第 17 章）' })
  expect(button).toBeTruthy()
  fireEvent.click(button)

  await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith(
    'project-1',
    'chapter-16',
    { seq: 17, mode: 'auto' },
  ))
  expect(onTaskStart).toHaveBeenCalledWith('task-17', undefined, 17, 'auto')
  expect((await screen.findByRole('status')).textContent).toContain('第 17 章写作任务已创建')
})

it('passes the optional writing instruction and exposes a request error', async () => {
  vi.mocked(api.generateChapter).mockRejectedValue(new ApiError(429, 'CONCURRENCY_LIMIT', null))

  render(
    <GenerationPanel
      projectId="project-1"
      chapters={[chapter]}
      selectedChapter={chapter}
      onTaskStart={() => {}}
    />,
  )

  fireEvent.change(screen.getByLabelText('写作指令（可留空）'), { target: { value: '承接上一章结尾' } })
  fireEvent.click(screen.getByRole('button', { name: '写下一章（第 17 章）' }))

  await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith(
    'project-1',
    'chapter-16',
    { seq: 17, mode: 'auto', user_instruction: '承接上一章结尾' },
  ))
  expect((await screen.findByRole('alert')).textContent).toContain('本书已有进行中的任务')
})

it('continues a failed empty placeholder instead of skipping to another chapter', async () => {
  vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'task-17b', trace_id: 'trace-17b', status: 'queued' })
  const placeholder: ChapterMeta = {
    id: 'chapter-17-writing',
    chapter_seq: 17,
    title: null,
    status: 'failed',
    word_count: 0,
    summary: null,
  }

  render(
    <GenerationPanel
      projectId="project-1"
      chapters={[chapter, placeholder]}
      selectedChapter={placeholder}
      onTaskStart={() => {}}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: '继续生成第 17 章' }))
  await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith(
    'project-1',
    'chapter-17-writing',
    { seq: 17, mode: 'auto' },
  ))
})

it('shows the target chapter as running and prevents a duplicate start', () => {
  const writing: ChapterMeta = {
    id: 'chapter-17-writing',
    chapter_seq: 17,
    title: null,
    status: 'writing',
    word_count: 0,
    summary: null,
  }

  render(
    <GenerationPanel
      projectId="project-1"
      chapters={[chapter, writing]}
      selectedChapter={writing}
      onTaskStart={() => {}}
    />,
  )

  expect(screen.getByText('当前生成：第 17 章')).toBeTruthy()
  expect((screen.getByRole('button', { name: '第 17 章生成中…' }) as HTMLButtonElement).disabled).toBe(true)
})

it('binds a batch task to its first chapter page', async () => {
  vi.mocked(api.generateBatch).mockResolvedValue({ task_id: 'batch-17', trace_id: 'trace-batch', status: 'queued' })
  const onTaskStart = vi.fn()

  render(
    <GenerationPanel
      projectId="project-1"
      chapters={[chapter]}
      selectedChapter={chapter}
      onTaskStart={onTaskStart}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: '发起批次' }))
  await waitFor(() => expect(api.generateBatch).toHaveBeenCalledWith(
    'project-1',
    { size: 3, start: 17 },
  ))
  expect(onTaskStart).toHaveBeenCalledWith('batch-17', 3, 17)
})

it('clears the previous book notice when switching projects', async () => {
  vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'task-17', trace_id: 'trace-17', status: 'queued' })
  const { rerender } = render(
    <GenerationPanel
      projectId="project-a"
      chapters={[chapter]}
      selectedChapter={chapter}
      onTaskStart={() => {}}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: '写下一章（第 17 章）' }))
  expect((await screen.findByRole('status')).textContent).toContain('第 17 章写作任务已创建')

  rerender(
    <GenerationPanel
      projectId="project-b"
      chapters={[]}
      selectedChapter={null}
      onTaskStart={() => {}}
    />,
  )
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.getByText('下一章：第 1 章')).toBeTruthy()
})

it('manual mode is sent with the chapter request and disables batch generation', async () => {
  vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'manual-17', trace_id: 'trace-manual', status: 'queued' })
  const onTaskStart = vi.fn()

  render(
    <GenerationPanel
      projectId="project-1"
      chapters={[chapter]}
      selectedChapter={chapter}
      onTaskStart={onTaskStart}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: '手动确认 Plan' }))
  expect((screen.getByLabelText('批次生成') as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: '发起批次' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText('手动模式需要逐章确认计划，批量生成已禁用。')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '写下一章（第 17 章）' }))
  await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith(
    'project-1',
    'chapter-16',
    { seq: 17, mode: 'manual' },
  ))
  expect(onTaskStart).toHaveBeenCalledWith('manual-17', undefined, 17, 'manual')
})


it.each(['next', 'rewrite', 'batch'] as const)('ignores a late %s response after switching projects', async (action) => {
  let finish!: (value: Awaited<ReturnType<typeof api.generateChapter>>) => void
  const pending = new Promise<Awaited<ReturnType<typeof api.generateChapter>>>(resolve => { finish = resolve })
  vi.mocked(api.generateChapter).mockReturnValue(pending)
  vi.mocked(api.generateBatch).mockReturnValue(pending)
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const onTaskStart = vi.fn()
  const props = { chapters: [chapter], selectedChapter: chapter, onTaskStart }
  const view = render(<GenerationPanel {...props} projectId="a" />)
  const label = action === 'next' ? '写下一章（第 17 章）' : action === 'rewrite' ? '重写第 16 章' : '发起批次'
  fireEvent.click(screen.getByRole('button', { name: label }))
  view.rerender(<GenerationPanel {...props} projectId="b" />)
  await act(async () => finish({ task_id: 'task-a', trace_id: 'trace-a', status: 'queued' }))
  expect(onTaskStart).not.toHaveBeenCalled()
  expect(screen.queryByRole('status')).toBeNull()
})

it('does not send a request after an old project preflight finishes', async () => {
  let finish!: (allowed: boolean) => void
  const beforeGenerate = () => new Promise<boolean>(resolve => { finish = resolve })
  const props = { chapters: [], selectedChapter: null, onTaskStart: vi.fn(), beforeGenerate }
  const view = render(<GenerationPanel {...props} projectId="a" />)
  fireEvent.click(screen.getByRole('button', { name: '写下一章（第 1 章）' }))
  view.rerender(<GenerationPanel {...props} projectId="b" />)
  await act(async () => finish(true))
  expect(api.generateChapter).not.toHaveBeenCalled()
})

it('does not clear the new project busy state when an old request fails', async () => {
  let fail!: (error: Error) => void
  vi.mocked(api.generateChapter).mockImplementation(pid => pid === 'a'
    ? new Promise((_resolve, reject) => { fail = reject }) : new Promise(() => {}))
  const props = { chapters: [], selectedChapter: null, onTaskStart: vi.fn() }
  const view = render(<GenerationPanel {...props} projectId="a" />)
  fireEvent.click(screen.getByRole('button', { name: '写下一章（第 1 章）' }))
  view.rerender(<GenerationPanel {...props} projectId="b" />)
  fireEvent.click(screen.getByRole('button', { name: '写下一章（第 1 章）' }))
  await act(async () => fail(new Error('old failure')))
  expect(screen.queryByRole('alert')).toBeNull()
  expect((screen.getByRole('button', { name: '发起中…' }) as HTMLButtonElement).disabled).toBe(true)
})
