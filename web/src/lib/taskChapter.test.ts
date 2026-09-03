// 右栏按章过滤纯函数单测（§11：批次按 :ch{seq} 子线程切 / 单章按 activeChapterSeq 对齐）。
import { describe, expect, it } from 'vitest'
import { chapterRunsOf, nodesForChapter, runsForChapter } from './taskChapter'
import type { AgentRun } from '../types'

const runs: AgentRun[] = [
  { task_id: 'batch:ch1', node: 'recall', model_id: null, input_tokens: 1, output_tokens: 1, cache_hit: false, duration_ms: 1, cost_est: 0.1, retry_count: 0, degraded: false, error: null, detail: null },
  { task_id: 'batch:ch2', node: 'persist', model_id: null, input_tokens: 1, output_tokens: 1, cache_hit: false, duration_ms: 1, cost_est: 0.2, retry_count: 0, degraded: false, error: null, detail: null },
  { task_id: 'batch:ch3', node: 'audit', model_id: null, input_tokens: 1, output_tokens: 1, cache_hit: false, duration_ms: 1, cost_est: 0.3, retry_count: 0, degraded: false, error: null, detail: null },
]

const nodes = [
  { taskId: 'batch:ch1', node: 'recall', seenAt: 1 },
  { taskId: 'batch:ch2', node: 'persist', seenAt: 2 },
]

describe('runsForChapter', () => {
  it('批次按 :ch{seq} 子线程切该章运行', () => {
    const out = runsForChapter(runs, {
      taskId: 'batch',
      batch: true,
      selectedSeq: 2,
      activeChapterSeq: null,
    })
    expect(out.map((r) => r.node)).toEqual(['persist'])
  })

  it('单章任务按 activeChapterSeq 对齐：匹配章全量，不匹配章为空', () => {
    const single = runs.slice(0, 1).map((r) => ({ ...r, task_id: 'single' }))
    const match = runsForChapter(single, {
      taskId: 'single',
      batch: false,
      selectedSeq: 1,
      activeChapterSeq: 1,
    })
    expect(match).toHaveLength(1)
    const miss = runsForChapter(single, {
      taskId: 'single',
      batch: false,
      selectedSeq: 2,
      activeChapterSeq: 1,
    })
    expect(miss).toHaveLength(0)
  })

  it('未选中章或无活动任务不过滤（整体兜底）', () => {
    expect(runsForChapter(runs, { taskId: 'batch', batch: true, selectedSeq: null })).toEqual(runs)
    expect(runsForChapter(runs, { taskId: null, batch: true, selectedSeq: 1 })).toEqual(runs)
  })
})

describe('nodesForChapter', () => {
  it('批次按 :ch{seq} 切实时节点流', () => {
    const out = nodesForChapter(nodes, {
      taskId: 'batch',
      batch: true,
      selectedSeq: 1,
      activeChapterSeq: null,
    })
    expect(out.map((n) => n.node)).toEqual(['recall'])
  })

  it('单章任务按 activeChapterSeq 对齐', () => {
    const out = nodesForChapter(nodes, {
      taskId: 'batch',
      batch: false,
      selectedSeq: 1,
      activeChapterSeq: 1,
    })
    expect(out).toEqual(nodes)
  })
})

describe('chapterRunsOf', () => {
  it('批次详情按 :ch{seq} 切片，单章任务全量', () => {
    expect(chapterRunsOf('batch_generate', 'batch', runs, 2).map((r) => r.node)).toEqual(['persist'])
    expect(chapterRunsOf('chapter_generate', 'single', runs, 1)).toHaveLength(3)
  })

  it('未选中章 → 全量', () => {
    expect(chapterRunsOf('batch_generate', 'batch', runs, null)).toEqual(runs)
  })
})
