import { expect, it } from 'vitest'
import { isHexColor } from './theme'
import { OFFICIAL_THEME_TOKENS, PINNED_WORKSPACE_PREVIEW } from './themePreview'

it('reads the official preview colors out of tokens.css', () => {
  // 预览的色全部从 tokens.css 解析而来。解析失败会静默变成空串，hexToRgba 也就跟着废掉，
  // 所以每一项都必须是写得出来的十六进制色——这也是「改了 CSS 预览就跟着走」的前提。
  for (const [id, tokens] of Object.entries(OFFICIAL_THEME_TOKENS)) {
    for (const [key, value] of Object.entries(tokens)) {
      expect(isHexColor(value), `${id} 的 ${key} 不是 hex：${JSON.stringify(value)}`).toBe(true)
    }
  }
})

it('pins the workspace preview to 万古魔尊 chapter one', () => {
  expect(PINNED_WORKSPACE_PREVIEW.book).toBe('万古魔尊')
  expect(PINNED_WORKSPACE_PREVIEW.title).toBe('第 1 章')
  expect(PINNED_WORKSPACE_PREVIEW.bookLinks).toEqual(['设定', '创作设置', '全局审计'])
  expect(PINNED_WORKSPACE_PREVIEW.chapters).toHaveLength(2)
  expect(PINNED_WORKSPACE_PREVIEW.body.startsWith('那道裂痕弯得太规整了')).toBe(true)
})
