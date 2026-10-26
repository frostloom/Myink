import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, fireEvent } from '@testing-library/vue'
import ChapterList from './components/ChapterList.vue'
afterEach(cleanup)
it('renders chapters arriving after the initial empty list and keeps selection interactive', async () => {
  const onSelect = vi.fn()
  const view = render(ChapterList, { props: { chapters: [], selectedCid: null, onSelect } })
  await view.rerender({ chapters: [{ id: 'c', chapter_seq: 1, title: '雨夜', summary: null, status: 'confirmed', word_count: 20 }] })
  const chapter = screen.getByRole('button', { name: /第 1 章.*雨夜/ })
  await fireEvent.click(chapter)
  expect(onSelect).toHaveBeenCalledWith('c')
})

import ChapterPlanPanel from './components/ChapterPlanPanel.vue'
import type { AgentRun, ChapterPlan } from '../../src/types'
const plan: ChapterPlan = { project_id: 'p', chapter_seq: 1, goals: ['原目标'], scenes: [], characters: [], hooks_to_plant: [], hooks_to_resolve: [], expected_events: ['事件'], hard_constraints: [], transition: { mode: 'continue', anchor_quote: '', pending_action: '', opening_beat: '开场', bridge: '' } }
const run: AgentRun = { task_id: 't', node: 'plan_chapter', model_id: 'stub', input_tokens: 0, output_tokens: 0, cache_hit: false, duration_ms: 1, cost_est: 0, retry_count: 0, degraded: false, error: null, detail: { plan, plan_attempt: 1, writing_mode: 'manual' } }
it('preserves the edited manual plan when a snapshot refresh repeats the same attempt', async () => {
  const view = render(ChapterPlanPanel, { props: { taskId: 't', chapterSeq: 1, status: 'awaiting_plan', runs: [run], artifact: null, onConfirmed: vi.fn(), onCancelled: vi.fn() } })
  const target = screen.getByLabelText(/本章目标/)
  await fireEvent.update(target, '尚未提交的目标')
  await view.rerender({ runs: [structuredClone(run)] })
  expect((target as HTMLTextAreaElement).value).toBe('尚未提交的目标')
})
