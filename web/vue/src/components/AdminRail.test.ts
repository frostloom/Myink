// @vitest-environment jsdom
import { render, screen, within, cleanup, fireEvent, waitFor } from '@testing-library/vue'
import { afterEach, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { authKey } from '../authContext'
import AdminRail from './AdminRail.vue'

afterEach(cleanup)
async function page(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { render: () => null } }] })
  await router.push(path)
  render(AdminRail, { global: { plugins: [router], provide: {
    [authKey as symbol]: { logout: vi.fn(), status: ref('authenticated'), session: ref({ role: 'admin', roleVerified: true }) },
  } } })
}

it('separates operational, membership, model-policy and writing-resource destinations', async () => {
  await page('/admin/model-routes')
  expect(within(screen.getByRole('navigation', { name: '用户与会员' })).getByRole('link', { name: '用户与会员' })).toBeTruthy()
  const modelNavigation = screen.getByRole('navigation', { name: '模型与策略' })
  expect(within(modelNavigation).getByRole('link', { name: '模型分配' }).getAttribute('aria-current')).toBe('page')
  expect(screen.getByRole('navigation', { name: '运营概览' })).toBeTruthy()
  expect(screen.getByRole('navigation', { name: '写作资源' })).toBeTruthy()
  expect(document.querySelectorAll('a[aria-current="page"]').length).toBe(1)
})

it('keeps the membership destination selected while reading an account detail', async () => {
  await page('/admin/users/member-id')
  expect(screen.getByRole('link', { name: '用户与会员' }).getAttribute('aria-current')).toBe('page')
  expect(document.querySelectorAll('a[aria-current="page"]').length).toBe(1)
})

it('marks only the overview destination as current, rather than the brand too', async () => {
  await page('/admin')
  expect(document.querySelectorAll('a[aria-current="page"]').length).toBe(1)
  expect(screen.getByRole('link', { name: '运营概览' }).getAttribute('aria-current')).toBe('page')
})

it('closes the compact navigation menu after selecting another destination', async () => {
  await page('/admin/model-routes')
  const menu = screen.getByLabelText('切换后台导航')
  await fireEvent.click(menu)
  expect(menu.getAttribute('aria-expanded')).toBe('true')
  await fireEvent.click(screen.getByRole('link', { name: 'AI 模型' }))
  await waitFor(() => expect(menu.getAttribute('aria-expanded')).toBe('false'))
})
