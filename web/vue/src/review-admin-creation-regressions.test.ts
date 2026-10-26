import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { h } from 'vue'
import { DetailPage } from './pages/admin/shared'
import { AdminTrends } from './pages/admin/AdminTrends'
import { RolePromptFields } from './pages/admin/RolePromptFields'
import { platformApi } from '../../src/lib/platformApi'
import { adminApi } from '../../src/lib/adminApi'
import * as echarts from 'echarts'
vi.mock('echarts', () => ({ init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })) }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks() })
it('keeps a labeled return link on administrator detail pages', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/admin/tasks/a')
  render({ render: () => h(DetailPage, { heading: '任务详情', backTab: 'tasks', children: [] }) }, { global: { plugins: [router] } })
  expect(screen.getByRole('link', { name: '返回' }).getAttribute('href')).toBe('/admin?tab=tasks')
})
it('initializes all three trend charts when their DOM hosts mount', async () => {
  vi.spyOn(adminApi, 'getTrends').mockResolvedValue({ start_date: '2026-01-01', end_date: '2026-01-01', timezone: 'UTC', items: [{ day: '2026-01-01', user_count: 2, project_count: 1, chapter_count: 3, task_count: 4, run_count: 5, input_tokens: 100, output_tokens: 75, cost_est: 0.25 }] })
  const view = render(AdminTrends, { props: { token: 'token', onForbidden: vi.fn() } })
  await screen.findByRole('img', { name: '每日估算费用' }); await flushPromises()
  expect(echarts.init).toHaveBeenCalledTimes(3)
  const charts = vi.mocked(echarts.init).mock.results.map(result => result.value)
  view.unmount()
  for (const chart of charts) expect(chart.dispose).toHaveBeenCalledOnce()
})

it('retains pixel spacing for administrator role prompt fields', async () => {
  vi.spyOn(platformApi, 'getPromptTemplates').mockResolvedValue([{ role: 'writer', templates: [{ id: 'system_write', title: '长篇正文写作', content: '', source: 'test', editable_content: '长篇要求', fixed_content: '固定协议' }] }])
  render(RolePromptFields, { props: { value: { role: 'writer', supplement: '', templates: {} }, onChange: vi.fn() } })
  const input = await screen.findByLabelText('各环节共用的补充要求')
  expect(input.closest('label')?.style.marginTop).toBe('24px')
  expect(input.closest('label')?.style.gap).toBe('8px')
  const stage = screen.getByDisplayValue('长篇要求') as HTMLTextAreaElement
  expect(stage.style.marginTop).toBe('8px')
  const contract = screen.getByText('系统保留的流程与输出格式').closest('details')
  expect(contract?.style.marginTop).toBe('16px')
})
