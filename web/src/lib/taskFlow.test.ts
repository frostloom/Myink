import { describe, expect, it } from 'vitest'
import { compactFlowRuns, groupFlowAttempts, liveStageNode, shortStageProgress } from './taskFlow'
import type { AgentRun } from '../types'

function run(node: string, overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    task_id: 'task-1',
    node,
    model_id: null,
    input_tokens: 0,
    output_tokens: 0,
    cache_hit: false,
    duration_ms: 0,
    cost_est: 0,
    retry_count: 0,
    degraded: false,
    error: null,
    detail: null,
    ...overrides,
  }
}

describe('compactFlowRuns', () => {
  it('merges wrapper and model records and keeps their complete usage totals', () => {
    const result = compactFlowRuns([
      run('validate', { duration_ms: 30, cost_est: 0.01, input_tokens: 120 }),
      run('validate', { duration_ms: 70, cost_est: 0.02, output_tokens: 80, cache_hit: true }),
    ], 'running')

    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({
      node: 'validate',
      duration_ms: 100,
      cost_est: 0.03,
      input_tokens: 120,
      output_tokens: 80,
      cache_hit: true,
    })
  })

  it('shows the route used by an old task that had no recorded route node', () => {
    const result = compactFlowRuns([
      run('audit', { detail: { audit_verdict: { verdict: 'pass', reasons: [], findings: [], confidence: 1 } } }),
      run('persist'),
    ], 'done')

    expect(result.map((item) => item.node)).toEqual(['audit', 'route', 'persist'])
    expect(result[1]).toMatchObject({ derived: true, detail: { route: 'persist' }, cost_est: 0 })
  })

  it('does not duplicate a route that was recorded by the current workflow', () => {
    const result = compactFlowRuns([
      run('audit'),
      run('route', { detail: { route: 'needs_review' } }),
    ], 'awaiting_review')

    expect(result.map((item) => item.node)).toEqual(['audit', 'route'])
  })
})

describe('groupFlowAttempts', () => {
  it('splits a reused task at each load_state and keeps prelude rows with the first attempt', () => {
    const grouped = groupFlowAttempts([
      run('batch_plan'), run('load_state'), run('write'), run('audit'), run('persist'),
      run('load_state'), run('write'), run('audit'), run('persist'),
      run('load_state'), run('write'), run('audit'), run('persist'),
    ])

    expect(grouped).toHaveLength(3)
    expect(grouped[0].map((item) => item.node)).toEqual([
      'batch_plan', 'load_state', 'write', 'audit', 'persist',
    ])
    expect(grouped[1].map((item) => item.node)).toEqual(['load_state', 'write', 'audit', 'persist'])
    expect(grouped[2].map((item) => item.node)).toEqual(['load_state', 'write', 'audit', 'persist'])
  })

  it('keeps a flow without load_state as one compatible attempt', () => {
    expect(groupFlowAttempts([run('write'), run('audit')])).toHaveLength(1)
  })
})

describe('liveStageNode', () => {
  const pending = { complete: false, failed: false }
  const complete = { complete: true, failed: false }

  it('reports the writing node while the plan is done and the write artifact still streams', () => {
    // 左侧已开始写正文、write 节点尚未落库：右栏应显示写作而非停在章节规划
    expect(liveStageNode([run('plan_chapter')], complete, pending)).toBe('write')
  })

  it('reports the plan node while the plan artifact streams', () => {
    expect(liveStageNode([run('load_state')], pending, null)).toBe('plan_chapter')
  })

  it('treats a second write-stage artifact after a recorded write as a revision', () => {
    expect(liveStageNode([run('write')], complete, pending)).toBe('revise')
  })

  it('stays empty once every artifact has settled', () => {
    expect(liveStageNode([run('plan_chapter'), run('write')], complete, complete)).toBeNull()
    expect(liveStageNode([], null, null)).toBeNull()
  })
})

describe('shortStageProgress', () => {
  it('scales char progress inside the 成稿 band, not across the whole ring', () => {
    // 成稿只占 0–70%：整篇写完了还有审稿和可能的改稿，直接把字数当总进度会冲到 100%
    expect(shortStageProgress({ stage: 'short_write', current: 0, total: 20000 })?.value).toBe(0)
    expect(shortStageProgress({ stage: 'short_write', current: 10000, total: 20000 })?.value)
      .toBeCloseTo(0.35)
    expect(shortStageProgress({ stage: 'short_write', current: 20000, total: 20000 })?.value)
      .toBeCloseTo(0.7)
  })

  it('parks at the stage floor when the step has no char count to report', () => {
    // 审稿/补写只报一条开始事件（total=0）——停在阶段起点，让环自己转
    const review = shortStageProgress({ stage: 'short_review', current: 0, total: 0 })
    expect(review?.value).toBeCloseTo(0.8)
    expect(review?.indeterminate).toBe(true)
  })

  it('is determinate while a step is reporting chars', () => {
    expect(shortStageProgress({ stage: 'short_revise', current: 1, total: 20000 })?.indeterminate)
      .toBe(false)
  })

  it('never exceeds the ring when a provider overruns the char budget', () => {
    // 目标 2 万字写成 2.6 万是常事（末章收不住），进度条不能因此超过 100%
    expect(shortStageProgress({ stage: 'short_revise', current: 26000, total: 20000 })?.value).toBe(1)
  })

  it('stays unknown until a stage arrives, and on stages this build does not know', () => {
    // 不按「上一步完了该轮到谁」猜阶段：猜错会显示成「正在补写」而实际在审稿
    expect(shortStageProgress(null)).toBeNull()
    expect(shortStageProgress({ stage: 'short_whatever', current: 5, total: 10 })).toBeNull()
  })
})
