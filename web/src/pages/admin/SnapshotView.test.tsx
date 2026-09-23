// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { adminApi, type AdminSnapshot } from '../../lib/adminApi'
import { SnapshotView } from './SnapshotView'

vi.mock('../../lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/adminApi')>()
  return { ...actual, adminApi: { ...actual.adminApi, getSnapshot: vi.fn() } }
})

function snapshot(overrides: Partial<AdminSnapshot> = {}): AdminSnapshot {
  return {
    id: 31, project_id: 'book-1', task_id: 'task-1', chapter_seq: 4, stage: 'write', attempt: 1,
    model_id: 'model-a', input_tokens: 2000, output_tokens: 3000, cache_hit: false,
    duration_ms: 4200, cost_est: 0.1234, retry_count: 0, degraded: false,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
    payload: {
      data: {
        _capture: { scope: 'snapshot', selective: true, truncated: false, redacted: false },
        prompt: {
          bytes: 4096, truncated: false,
          sections: [
            { role: 'system', name: '题材参考文档', policy: 'hash', bytes: 3000, sha256: 'b'.repeat(64) },
            { role: 'system', name: '世界观硬约束', policy: 'full', text: '灵气不可外放' },
          ],
        },
        output: { bytes: 5200, sha256: 'c'.repeat(64), excerpt: '他踏进山门。' },
      },
      truncated: true, redacted: false,
      limits: { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 },
    },
    snapshot_missing: false,
    ...overrides,
  }
}

function renderSnapshot() {
  return render(<SnapshotView token="token-admin" snapshotId={31} onForbidden={vi.fn()} />)
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('marks hash-only sections as retained by hash and never invents their text', async () => {
  vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot())
  renderSnapshot()

  expect(await screen.findByText('选择性留存')).toBeTruthy()
  expect(screen.getByText('内容已截断')).toBeTruthy()
  expect(screen.getByText('仅存哈希')).toBeTruthy()
  expect(screen.getByText('题材参考文档')).toBeTruthy()
  expect(screen.getByText(/原文未留存，仅 3000 字节/)).toBeTruthy()
  expect(screen.getByText('灵气不可外放')).toBeTruthy()
  expect(screen.getByText('他踏进山门。')).toBeTruthy()
})

it('offers only the sub-views this stage actually captured', async () => {
  vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot({
    stage: 'recall',
    payload: {
      data: {
        recall: {
          counts: { long_term_facts: 1 }, stats: { share: 0.5 },
          groups: { long_term_facts: [{ fact_id: 'f1', content: '灵气不可外放', is_hard: true }] },
        },
      },
      truncated: false, redacted: false,
      limits: { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 },
    },
  }))
  renderSnapshot()

  const nav = await screen.findByRole('navigation', { name: '快照子视图' })
  expect(nav.textContent).toBe('召回文本块硬规则')
  expect(screen.getByRole('button', { name: '召回文本块' }).getAttribute('aria-pressed')).toBe('true')

  fireEvent.click(screen.getByRole('button', { name: '硬规则' }))
  expect(await screen.findByText('灵气不可外放')).toBeTruthy()
  expect(screen.getByText('台账侧标了硬约束的事实（1）')).toBeTruthy()
  expect(screen.queryByText('提示词')).toBeNull()
})

it('tells the operator a legacy row has no payload instead of showing empty tables', async () => {
  vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot({
    snapshot_missing: true,
    payload: {
      data: null, truncated: false, redacted: false,
      limits: { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 },
    },
  }))
  renderSnapshot()

  expect(await screen.findByText('这条记录早于快照上线，只剩标量遥测。')).toBeTruthy()
  expect(screen.queryByRole('navigation', { name: '快照子视图' })).toBeNull()
  expect(screen.getByText(/写作 · 第 4 章 · 第 1 次/)).toBeTruthy()
})

it('reloads the same snapshot when asked to refresh', async () => {
  vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot())
  renderSnapshot()
  await screen.findByText('选择性留存')

  fireEvent.click(screen.getByRole('button', { name: '刷新当前视图' }))

  await waitFor(() => expect(adminApi.getSnapshot).toHaveBeenCalledTimes(2))
  expect(adminApi.getSnapshot).toHaveBeenLastCalledWith('token-admin', 31, expect.any(AbortSignal))
})
