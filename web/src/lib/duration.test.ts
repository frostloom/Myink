import { expect, it } from 'vitest'
import { formatDuration } from './duration'

it('不足一秒给毫秒，不做小数保留', () => {
  expect(formatDuration(0)).toBe('0 ms')
  expect(formatDuration(640)).toBe('640 ms')
})

it('一分钟内给一位小数的秒', () => {
  expect(formatDuration(1000)).toBe('1.0 秒')
  expect(formatDuration(12_340)).toBe('12.3 秒')
  expect(formatDuration(59_900)).toBe('59.9 秒')
})

it('过一分钟给分秒；秒数进位到 60 时向上并成整分', () => {
  expect(formatDuration(60_000)).toBe('1 分 0 秒')
  expect(formatDuration(132_310)).toBe('2 分 12 秒')
  expect(formatDuration(119_600)).toBe('2 分 0 秒')
})