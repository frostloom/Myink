// 卡片跳哪去由形态决定：长篇草稿回到长篇向导续填；短篇一律进工作台
// （短篇没有「设定 → 大纲」两步可回填，回到对话页也接不上——对话页只能从头聊）。
import { expect, it } from 'vitest'
import { isProjectDraft, projectHref } from './projectCreation'
import type { Project } from '../types'

function project(overrides: Partial<Project>): Project {
  return { id: 'p1', title: '书', genre: '悬疑', current_chapter: 0, target_words: null, ...overrides }
}

it('sends a short book to the workspace even while it is a draft', () => {
  const short = project({ creation_status: 'draft', form: 'short' })
  expect(projectHref(short)).toBe('/projects/p1')
  expect(projectHref(project({ creation_status: 'setup_confirmed', form: 'short' }))).toBe('/projects/p1')
  expect(projectHref(project({ creation_status: 'ready', form: 'short' }))).toBe('/projects/p1')
})

it('treats a missing form as long-form', () => {
  // 老数据没有 form 字段；缺省是长篇（与后端 ProjectOut.form 默认一致）。
  expect(projectHref(project({ creation_status: 'draft' }))).toBe('/long/new?draft=p1')
  expect(projectHref(project({ creation_status: 'draft', form: 'long' }))).toBe('/long/new?draft=p1')
})

it('sends a finished book to the workspace regardless of form', () => {
  // 工作台自己按 project.form 分叉，路由不区分形态。
  expect(projectHref(project({ creation_status: 'ready', form: 'short' }))).toBe('/projects/p1')
  expect(projectHref(project({ creation_status: 'legacy_ready', form: 'long' }))).toBe('/projects/p1')
})

it('escapes the draft id', () => {
  expect(projectHref(project({ id: 'a/b', creation_status: 'draft' }))).toBe('/long/new?draft=a%2Fb')
})

it('counts both draft states as drafts', () => {
  expect(isProjectDraft(project({ creation_status: 'draft' }))).toBe(true)
  expect(isProjectDraft(project({ creation_status: 'setup_confirmed' }))).toBe(true)
  expect(isProjectDraft(project({ creation_status: 'ready' }))).toBe(false)
})
