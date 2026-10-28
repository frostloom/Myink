// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { afterEach, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ModelRoutingBoard from './ModelRoutingBoard.vue'

afterEach(cleanup)
const global = { stubs: { RouterLink: true } }
const props = {
  roles: [{ key: 'writer', label: '写作' }, { key: 'planner', label: '规划' }, { key: 'audit', label: '审核' }],
  connections: [
    { id: 'basic', name: '基础模型', model: 'basic', enabled: true, minimum_tier: 'normal' as const },
    { id: 'premium', name: '高级模型', model: 'pro', enabled: true, minimum_tier: 'vip' as const },
    { id: 'disabled', name: '停用模型', model: 'old', enabled: false },
  ],
  normalRoutes: { writer: 'custom:basic', audit: 'custom:basic' },
  vipRoutes: { writer: 'custom:premium' },
  weights: { vip: 3, normal: 1 },
}

it('compares real effective models and distinguishes VIP writer inheritance from normal role inheritance', () => {
  render(ModelRoutingBoard, { props, global })
  const planner = screen.getByRole('row', { name: /规划/ })
  const cells = within(planner).getAllByRole('cell')
  expect(cells[0].textContent).toContain('默认模型：基础模型')
  expect(cells[1].textContent).toContain('默认模型：高级模型')
  expect(cells[1].textContent).toContain('跟随 VIP 写作模型')
  const audit = screen.getByRole('row', { name: /审核/ })
  expect(within(audit).getAllByRole('cell')[1].textContent).toContain('默认模型：基础模型')
  expect(within(audit).getAllByRole('cell')[1].textContent).toContain('沿用普通用户的审核分配')
  expect(within(screen.getByLabelText('写作')).queryByRole('option', { name: /高级模型/ })).toBeNull()
  expect(within(screen.getByLabelText('VIP 写作默认模型')).getByRole('option', { name: /高级模型/ })).toBeTruthy()
  expect(screen.queryByRole('option', { name: '停用模型' })).toBeNull()
})

it('emits edits without mutating the existing policy and removes an explicit VIP override when inheritance is selected', async () => {
  const wrapper = mount(ModelRoutingBoard, { props, global })
  await wrapper.get('[aria-label="VIP 审核默认模型"]').setValue('custom:premium')
  expect(wrapper.emitted('update:vipRoutes')?.[0]).toEqual([{ writer: 'custom:premium', audit: 'custom:premium' }])
  await wrapper.get('[aria-label="VIP 写作默认模型"]').setValue('')
  expect(wrapper.emitted('update:vipRoutes')?.[1]).toEqual([{}])
  expect(props.vipRoutes).toEqual({ writer: 'custom:premium' })
})

it('shows scheduling shares and keeps a positive ordinary-user opportunity', async () => {
  render(ModelRoutingBoard, { props, global })
  expect(screen.getByRole('img', { name: 'VIP 75%，普通用户 25% 的调度份额' })).toBeTruthy()
  await fireEvent.update(screen.getByLabelText('VIP 调度权重'), '4')
  expect(screen.getByLabelText('普通用户调度权重').getAttribute('min')).toBe('1')
})
