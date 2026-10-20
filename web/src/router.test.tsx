// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { RouterProvider } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { useAuth } from './context/AuthContext'
import { router } from './router'

vi.mock('./context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('./components/FeedbackWidget', () => ({ FeedbackWidget: () => null, AttachmentChip: () => null }))
vi.mock('./lib/adminApi', async (original) => {
  const actual = await original<typeof import('./lib/adminApi')>()
  return { ...actual, adminApi: { ...actual.adminApi, getOverview: vi.fn().mockResolvedValue(null) } }
})

const session = {
  token: 'admin-token', userId: 'admin', username: 'root', tier: 'normal',
  role: 'admin' as const, roleVerified: true, expiresAt: Date.now() + 60_000,
}

function authenticate(overrides = {}) {
  vi.mocked(useAuth).mockReturnValue({
    session, status: 'authenticated', logout: vi.fn(), revalidate: vi.fn(),
    login: vi.fn().mockResolvedValue({ status: 'authenticated' }), ...overrides,
  } as unknown as ReturnType<typeof useAuth>)
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('lands a verified administrator on the administration home from root', async () => {
  authenticate()
  await act(() => router.navigate('/'))
  render(<RouterProvider router={router} />)
  await screen.findByRole('navigation', { name: '平台管理导航' })
  expect(router.state.location.pathname).toBe('/admin')
})

it('lands a verified administrator on administration after password login', async () => {
  authenticate()
  await act(() => router.navigate('/login'))
  render(<RouterProvider router={router} />)
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'root' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: '登录' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/admin'))
})

it('lands a verified administrator on administration after MFA verification', async () => {
  authenticate({
    login: vi.fn().mockResolvedValue({ status: 'mfa', mfaToken: 'challenge' }),
    completeMfa: vi.fn().mockResolvedValue(true),
  })
  await act(() => router.navigate('/login'))
  render(<RouterProvider router={router} />)
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'root' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: '登录' }))
  await screen.findByLabelText('验证码')
  fireEvent.change(screen.getByLabelText('验证码'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: '验证' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/admin'))
})
