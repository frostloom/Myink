// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ArtifactState } from '../hooks/useTaskEvents'
import { api } from '../lib/api'
import type { AgentRun, ChapterPlan } from '../types'
import { ChapterPlanPanel } from './ChapterPlanPanel'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: { ...actual.api, confirmTaskPlan: vi.fn(), cancelTask: vi.fn() },
  }
})

function plan(goal: string): ChapterPlan {
  return {
    project_id: 'project-1', chapter_seq: 17,
    goals: [goal],
    scenes: [{ location_id: '东峰', participants: ['林尘'], goal: '查证线索', time: '清晨' }],
    characters: [], hooks_to_plant: [], hooks_to_resolve: [],
    expected_events: ['林尘确认吊坠纹路'], hard_constraints: ['不得升级'],
    transition: {
      mode: 'continue', anchor_quote: '他握紧残片。', pending_action: '查清纹路',
      opening_beat: '林尘沿着章尾动作抬头观察吊坠。', bridge: '',
    },
  }
}

function run(attempt: number, value: ChapterPlan): AgentRun {
  return {
    task_id: 'task-17', node: 'plan_chapter', model_id: 'stub',
    input_tokens: 1, output_tokens: 1, cache_hit: false, duration_ms: 1,
    cost_est: 0, retry_count: 0, degraded: false, error: null,
    detail: { plan: value, plan_attempt: attempt, writing_mode: 'manual' },
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('lets the user edit the current manual plan before write starts', async () => {
  vi.mocked(api.confirmTaskPlan).mockResolvedValue({ task_id: 'task-17', status: 'queued' })
  const onConfirmed = vi.fn()
  render(<ChapterPlanPanel
    taskId="task-17" chapterSeq={17} status="awaiting_plan"
    runs={[run(1, plan('旧目标'))]} artifact={null}
    onConfirmed={onConfirmed} onCancelled={() => {}}
  />)

  fireEvent.change(screen.getByLabelText(/本章目标/), { target: { value: '用户修订后的目标' } })
  fireEvent.click(screen.getByRole('button', { name: '确认计划并开始写作' }))

  await waitFor(() => expect(api.confirmTaskPlan).toHaveBeenCalledTimes(1))
  const [, submitted, expectedAttempt] = vi.mocked(api.confirmTaskPlan).mock.calls[0]
  expect(submitted.goals).toEqual(['用户修订后的目标'])
  expect(expectedAttempt).toBe(1)
  expect(onConfirmed).toHaveBeenCalledWith('task-17', 17)
})

it('shows a streaming replan while folding the previous plan into history', () => {
  const artifact: ArtifactState = {
    artifactId: 'plan-v2', taskId: 'task-17', stage: 'plan', chapterSeq: 17,
    attempt: 2, content: '{"goals":["新版计划正在生成', complete: false,
    failed: false, artifact: null, message: null,
  }
  render(<ChapterPlanPanel
    taskId="task-17" chapterSeq={17} status="running"
    runs={[run(1, plan('旧版目标'))]} artifact={artifact}
    onConfirmed={() => {}} onCancelled={() => {}}
  />)

  expect(screen.getByText('AI 正在规划')).toBeTruthy()
  expect(screen.getByText('历史计划（1）')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '确认计划并开始写作' })).toBeNull()
})

it('can cancel a task that is waiting for plan confirmation', async () => {
  vi.mocked(api.cancelTask).mockResolvedValue({ task_id: 'task-17', status: 'cancelled' })
  const onCancelled = vi.fn()
  render(<ChapterPlanPanel
    taskId="task-17" chapterSeq={17} status="awaiting_plan"
    runs={[run(1, plan('目标'))]} artifact={null}
    onConfirmed={() => {}} onCancelled={onCancelled}
  />)

  fireEvent.click(screen.getByRole('button', { name: '取消本次写作' }))
  await waitFor(() => expect(api.cancelTask).toHaveBeenCalledWith('task-17'))
  expect(onCancelled).toHaveBeenCalledWith('task-17', 17)
})
