// 扫榜源展示映射纯函数单测：source 标签/色调 + tags/hot 格式化兜底。
import { describe, expect, it } from 'vitest'
import { hotText, sourceLabel, sourceTone, tagsText } from './rankings'

describe('sourceLabel / sourceTone', () => {
  it('已知 source 有中文标签', () => {
    expect(sourceLabel('remote')).toBe('实时榜单')
    expect(sourceLabel('sample')).toBe('样例数据')
  })

  it('未知 source 回退原始字符串', () => {
    expect(sourceLabel('fanqie')).toBe('fanqie')
  })

  it('remote 用 accent（真实源），sample 用 warning（降级）', () => {
    expect(sourceTone('remote')).toBe('accent')
    expect(sourceTone('sample')).toBe('warning')
    expect(sourceTone('fanqie')).toBe('warning')
  })
})

describe('tagsText / hotText', () => {
  it('tags 顿号连接，缺失/空安全', () => {
    expect(tagsText(['修仙', '凡人'])).toBe('修仙、凡人')
    expect(tagsText([])).toBe('')
    expect(tagsText(undefined)).toBe('')
  })

  it('hot 去首尾空白，空值回退空串', () => {
    expect(hotText(' 12.3万 ')).toBe('12.3万')
    expect(hotText('')).toBe('')
    expect(hotText(null)).toBe('')
    expect(hotText(undefined)).toBe('')
  })
})
