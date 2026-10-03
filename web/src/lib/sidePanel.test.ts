// @vitest-environment jsdom
// 右栏默认收起是这次改版的正面收益（正文列回到 720px），所以「没存过 = 收起」要钉住。
import { beforeEach, expect, it } from 'vitest'
import { readSidePanelOpen, writeSidePanelOpen } from './sidePanel'

beforeEach(() => localStorage.clear())

it('starts collapsed when nothing was stored', () => {
  expect(readSidePanelOpen()).toBe(false)
})

it('keeps the choice across reloads in both directions', () => {
  writeSidePanelOpen(true)
  expect(readSidePanelOpen()).toBe(true)
  writeSidePanelOpen(false)
  expect(readSidePanelOpen()).toBe(false)
})

it('treats an unrecognised value as collapsed', () => {
  localStorage.setItem('myink.sidePanel', 'yes')
  expect(readSidePanelOpen()).toBe(false)
})
