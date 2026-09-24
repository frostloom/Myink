// 短篇审稿报告。决策文档 §8 那条风险：短篇没有全局审计，审稿是全篇唯一的出口，
// 不显示（尤其是不显示「按通过处理」这类降级说明）用户就会以为「审过了没问题」。
// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import type { AgentRun, Finding } from '../types'
import { ShortStoryPanel } from './ShortStoryPanel'

afterEach(cleanup)

function reviewRun(detail: NonNullable<AgentRun['detail']>): AgentRun {
  return {
    task_id: 'task-short',
    node: 'short_review',
    model_id: 'deepseek-chat',
    input_tokens: 100,
    output_tokens: 200,
    cache_hit: false,
    duration_ms: 1000,
    cost_est: 0.1,
    retry_count: 0,
    degraded: false,
    error: null,
    detail,
  }
}

const lengthFinding: Finding = {
  conflict_key: 'short-len:2',
  conflict_type: 'style',
  severity: 'hint',
  scope: 'local',
  source: 'L1',
  evidence: [{ chapter: 2, quote: '第 2 章正文 1200 字，目标 2000 字（区间 1600–2600）' }],
  suggestion: '第 2 章 短于目标：1200 字 / 2000 字',
}

it('says the story has not been reviewed yet before the task has run', () => {
  render(<ShortStoryPanel runs={[]} />)

  expect(screen.getByText('本篇还没有审稿记录。')).toBeTruthy()
})

it('shows the reviewer verdict with its issues and suggestions', () => {
  render(<ShortStoryPanel runs={[reviewRun({
    short_review: {
      verdict: 'revise',
      issues: ['第 3 章中段节奏塌了'],
      suggestions: ['把第 3 章的追逐压缩成半章'],
      warning: null,
    },
    empty_chapters: [],
    length_findings: [],
    revised: true,
  })]} />)

  expect(screen.getByText('已改稿')).toBeTruthy()
  expect(screen.getByText('第 3 章中段节奏塌了')).toBeTruthy()
  expect(screen.getByText('把第 3 章的追逐压缩成半章')).toBeTruthy()
})

it('keeps the revise verdict visible when the rewrite did not land', () => {
  render(<ShortStoryPanel runs={[reviewRun({
    short_review: { verdict: 'revise', issues: ['整体太平'], suggestions: [], warning: '改稿未完成（超时），已保留首稿' },
    empty_chapters: [],
    length_findings: [],
    revised: false,
  })]} />)

  expect(screen.getByText('审稿要求改稿')).toBeTruthy()
  expect(screen.getByText('改稿未完成（超时），已保留首稿')).toBeTruthy()
})

it('shows the degraded-review warning on a pass so it does not read as a clean bill', () => {
  render(<ShortStoryPanel runs={[reviewRun({
    short_review: { verdict: 'pass', issues: [], suggestions: [], warning: '审稿未完成（timeout），这一篇按通过处理' },
    empty_chapters: [],
    length_findings: [],
    revised: false,
  })]} />)

  expect(screen.getByText('通过')).toBeTruthy()
  expect(screen.getByText('审稿未完成（timeout），这一篇按通过处理')).toBeTruthy()
  expect(screen.getByText('未发现需要改稿的问题。')).toBeTruthy()
})

it('lists the chapters that came out empty and the ones off their length target', () => {
  render(<ShortStoryPanel runs={[reviewRun({
    short_review: { verdict: 'pass', issues: [], suggestions: [], warning: null },
    empty_chapters: [3, 5],
    length_findings: [lengthFinding],
    revised: false,
  })]} />)

  expect(screen.getByText('第 3、5 章没有正文')).toBeTruthy()
  expect(screen.getByText('第 2 章正文 1200 字，目标 2000 字（区间 1600–2600）')).toBeTruthy()
})