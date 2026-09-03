// 建书题材标签组合纯函数单测（§7.11 建书向导）：parse 切分去重 + toggle 追加/移除/复合。
import { describe, expect, it } from 'vitest'
import { parseGenres, toggleGenre } from './genres'

describe('parseGenres', () => {
  it('空串与纯空白 → 空列表', () => {
    expect(parseGenres('')).toEqual([])
    expect(parseGenres('   ')).toEqual([])
  })

  it('按全角/半角逗号切分并去重', () => {
    expect(parseGenres('仙侠,都市，仙侠')).toEqual(['仙侠', '都市'])
  })

  it('首尾空白清除', () => {
    expect(parseGenres(' 都市 ， 修仙 ')).toEqual(['都市', '修仙'])
  })
})

describe('toggleGenre', () => {
  it('追加新标签', () => {
    expect(toggleGenre('', '仙侠')).toBe('仙侠')
    expect(toggleGenre('都市', '修仙')).toBe('都市，修仙')
  })

  it('移除已有标签', () => {
    expect(toggleGenre('都市，修仙', '都市')).toBe('修仙')
    expect(toggleGenre('仙侠', '仙侠')).toBe('')
  })

  it('复合标签来回切换', () => {
    let g = toggleGenre('', '都市')
    g = toggleGenre(g, '修仙')
    expect(g).toBe('都市，修仙')
    g = toggleGenre(g, '都市')
    expect(g).toBe('修仙')
  })
})
