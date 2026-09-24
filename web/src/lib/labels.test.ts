// 节点名 → 中文标签：短篇那四个节点自成一套，漏一条时间线就直接显示 short_write。
import { expect, it } from 'vitest'
import { nodeLabel, taskChapterLabel, taskTypeLabel } from './labels'

it('names the four steps of the short-form pipeline', () => {
  expect(['short_write', 'short_continue', 'short_review', 'short_revise'].map(nodeLabel))
    .toEqual(['成稿', '补写空章', '审稿', '改稿'])
})

it('names the short plan nodes and the short task type too', () => {
  // 短篇的建书动线除了 book_setup，还自己记两条：出方案 + 审纲。
  expect(['short_plan', 'short_plan_review'].map(nodeLabel)).toEqual(['方案生成', '审纲'])
  expect(taskTypeLabel('short_generate')).toBe('短篇生成')
})

it('does not call a short task a whole batch', () => {
  // 短篇任务的 chapter_seq 也是空，但它不是批次：管理面板上写「整批」是错的。
  expect(taskChapterLabel({ task_type: 'short_generate', chapter_seq: null })).toBe('整篇')
  expect(taskChapterLabel({ task_type: 'batch_generate', chapter_seq: null })).toBe('整批')
  expect(taskChapterLabel({ task_type: 'chapter_generate', chapter_seq: 3 })).toBe('第 3 章')
})