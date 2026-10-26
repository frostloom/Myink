import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, fireEvent } from '@testing-library/vue'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import RouteBoundary from './RouteBoundary.vue'
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('contains render errors without exposing stack and recovers after home navigation', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/broken')
  const Child = defineComponent({ setup: () => () => { if (router.currentRoute.value.path === '/broken') throw new Error('private diagnostic'); return h('p', '恢复页面') } })
  render(RouteBoundary, { slots: { default: Child }, global: { plugins: [router] } })
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByText('private diagnostic')).toBeNull()
  await fireEvent.click(screen.getByRole('link', { name: '回到首页' }))
  expect(await screen.findByText('恢复页面')).toBeTruthy()
})
