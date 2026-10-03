// @vitest-environment jsdom
// metricEntries 是一条读数带的唯一口径：概览页与用户详情共用它，标签、顺序、格式化都不能漂。
import { expect, it } from 'vitest'
import { metricEntries } from './shared'
import type { AdminMetrics } from '../../lib/adminApi'

const value = {
  run_count: 1234, input_tokens: 638199, output_tokens: 215793, cost_est: 0.803, duration_ms: 1323310,
} as AdminMetrics

it('lists the five usage readings in label/value order', () => {
  expect(metricEntries(value)).toEqual([
    ['运行数', '1,234'],
    ['输入 token', '638,199'],
    ['输出 token', '215,793'],
    ['预估成本', '0.8030'],
    ['节点耗时', '22 分 3 秒'],
  ])
})

it('keeps the zero-duration dash rather than printing 0 ms', () => {
  const zero = metricEntries({ ...value, run_count: 0, duration_ms: 0 })
  expect(zero[0][1]).toBe('0')
  expect(zero[4]).toEqual(['节点耗时', '—'])
})
