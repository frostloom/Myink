import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import GuestShell from './GuestShell.vue'
afterEach(cleanup)
it('blocks actions and submits, allows rail navigation and registration', async () => {
  const action = vi.fn()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/long')
  render(GuestShell, { slots: { default: { template: '<form @submit.prevent="action"><button @click="action">生成</button><input aria-label="内容" /><a data-guest-exempt href="#nav">导航</a></form>', setup: () => ({ action }) } }, global: { plugins: [router] } })
  await fireEvent.click(screen.getByRole('button', { name: '生成' }))
  expect(action).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog')).toBeTruthy()
  await fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  await fireEvent.click(screen.getByText('导航'))
  expect(screen.queryByRole('dialog')).toBeNull()
  await fireEvent.submit(screen.getByRole('textbox').closest('form')!)
  expect(action).not.toHaveBeenCalled()
  await fireEvent.click(screen.getByRole('button', { name: '注册' }))
  await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/login?mode=register'))
})
