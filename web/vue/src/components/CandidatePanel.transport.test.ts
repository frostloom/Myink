// @vitest-environment jsdom
import { h, nextTick } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '../workspaceTestUtils'
import CandidatePanel from './CandidatePanel.vue'
import type { MemoryCandidate } from '../../../src/types'

const candidate: MemoryCandidate = { candidate_id: 'c', kind: 'fact', source_chapter: 1, payload: { content: '伤势痊愈' }, confidence: 1, status: 'pending', created_at: null }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

// Exercise the real API client against the current server contract; the removed
// gateway's /batches/* aliases must not be used for chapter or batch review.
it.each([false, true])('continues accepted review through the task endpoint (batch=%s)', async batch => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    requests.push(url)
    if (url === '/api/v1/projects/p/candidates/c/confirm') return new Response('{}')
    if (url === '/api/v1/tasks/t/resume') return new Response('{"task_id":"t","status":"queued"}')
    return new Response('{"error":"not_found"}', { status: 404 })
  }))
  const released = vi.fn()
  render(h(CandidatePanel, { projectId: 'p', candidates: [candidate], onChanged: () => {}, onReleased: released, releaseTarget: { taskId: 't', chapterSeq: 1, ...(batch ? { batchSize: 3 } : {}) } }))
  await fireEvent.click(screen.getByRole('button', { name: '接受' }))
  await waitFor(() => expect(released).toHaveBeenCalledWith('t', 1, batch ? 3 : undefined))
  expect(requests).toEqual(['/api/v1/projects/p/candidates/c/confirm', '/api/v1/tasks/t/resume'])
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByRole('progressbar')).toBeNull()
})

it('reopens accepted review and retries continuation without accepting again', async () => {
  let attempts = 0
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    requests.push(url)
    if (url === '/api/v1/tasks/t/resume') {
      attempts++
      return attempts === 1 ? new Response('{"error":"offline"}', { status: 503 }) : new Response('{}')
    }
    return new Response('{"error":"not_found"}', { status: 404 })
  }))
  const released = vi.fn()
  render(h(CandidatePanel, { projectId: 'p', candidates: [{ ...candidate, status: 'confirmed' }], onChanged: () => {}, onReleased: released, releaseTarget: { taskId: 't', chapterSeq: 1 } }))
  await fireEvent.click(screen.getByRole('button', { name: '重试完成确认' }))
  await screen.findByText('offline')
  await fireEvent.click(screen.getByRole('button', { name: '暂后处理' }))
  await fireEvent.click(screen.getByRole('button', { name: /设定确认/ }))
  await fireEvent.click(screen.getByRole('button', { name: '继续处理' }))
  await fireEvent.click(screen.getByRole('button', { name: '重试完成确认' }))
  await waitFor(() => expect(released).toHaveBeenCalledOnce())
  expect(requests).toEqual(['/api/v1/tasks/t/resume', '/api/v1/tasks/t/resume'])
})

it.each([false, true])('saves rejection once and retries revision through the task endpoint (batch=%s)', async batch => {
  const requests: string[] = []
  let attempts = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    requests.push(url)
    if (url === '/api/v1/projects/p/tasks?chapter_seq=1') return new Response(JSON.stringify([
      { task_id: 't', task_type: batch ? 'batch_generate' : 'chapter_generate', status: 'awaiting_review', batch_size: batch ? 3 : null },
    ]))
    if (url === '/api/v1/tasks/t') return new Response('{"payload":{"start":1},"progress":{"current":0}}')
    if (url === '/api/v1/projects/p/candidates/c/reject') return new Response('{}')
    if (url === '/api/v1/tasks/t/resume') {
      attempts++
      return attempts === 1 ? new Response('{"error":"offline"}', { status: 503 }) : new Response('{}')
    }
    return new Response('{"error":"not_found"}', { status: 404 })
  }))
  const released = vi.fn()
  render(h(CandidatePanel, { projectId: 'p', candidates: [candidate], onChanged: () => {}, onReleased: released }))
  await fireEvent.click(screen.getByRole('button', { name: '不接受，自动修改' }))
  await screen.findByText(/意见已保存，但自动修改未能启动/)
  await fireEvent.click(screen.getByRole('button', { name: '重试修改第 1 章' }))
  await waitFor(() => expect(released).toHaveBeenCalledWith('t', 1, batch ? 3 : undefined, 'revise'))
  expect(requests.filter(url => url.endsWith('/reject'))).toHaveLength(1)
  expect(requests.filter(url => url.endsWith('/resume'))).toEqual(['/api/v1/tasks/t/resume', '/api/v1/tasks/t/resume'])
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('uses a modal dialog and only honors cancellation while review is idle', async () => {
  let finish!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
  render(h(CandidatePanel, { projectId: 'p', candidates: [candidate], onChanged: () => {} }))
  const dialog = screen.getByRole('dialog', { name: '设定确认' })
  expect(dialog.tagName).toBe('DIALOG')
  dialog.dispatchEvent(new Event('cancel', { cancelable: true })); await nextTick()
  expect(screen.queryByRole('dialog')).toBeNull()
  await fireEvent.click(screen.getByRole('button', { name: '处理 1 项设定' }))
  await fireEvent.click(screen.getByRole('button', { name: '接受' }))
  const pendingDialog = screen.getByRole('dialog', { name: '设定确认' })
  pendingDialog.dispatchEvent(new Event('cancel', { cancelable: true })); await nextTick()
  expect(screen.getByRole('dialog')).toBe(pendingDialog)
  expect((screen.getByRole('button', { name: '暂后处理' }) as HTMLButtonElement).disabled).toBe(true)
  finish(new Response('{"error":"offline"}', { status: 503 }))
  await screen.findByText('offline')
  pendingDialog.dispatchEvent(new Event('cancel', { cancelable: true })); await nextTick()
  expect(screen.queryByRole('dialog')).toBeNull()
})

it.each(['接受','不接受，自动修改'])('announces pending review action %s and removes the wait on failure', async name => {
 let finish!: (response: Response) => void
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve})))
 render(h(CandidatePanel,{projectId:'p',candidates:[candidate],onChanged:()=>{}}))
 await fireEvent.click(screen.getByRole('button',{name}))
 expect(screen.getByRole('status').textContent).toContain(name==='接受'?'正在提交设定确认':'正在提交修改意见并启动修订')
 expect(screen.getByRole('progressbar').hasAttribute('value')).toBe(false)
 finish(new Response('{"error":"offline"}',{status:503}))
 await screen.findByText('offline')
 expect(screen.queryByRole('progressbar')).toBeNull()
})
