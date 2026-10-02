// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import AccountPage from './AccountPage'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../lib/api', async (original) => {
  const actual = await original<typeof import('../lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      listProjects: vi.fn(),
      mfaStatus: vi.fn(),
      mfaEnroll: vi.fn(),
      mfaConfirm: vi.fn(),
      mfaDisable: vi.fn(),
    },
  }
})

const ADMIN_SESSION = {
  token: 'token-a', userId: 'admin-a', username: 'root', tier: 'normal', role: 'admin' as const,
  roleVerified: true, expiresAt: Date.now() + 60_000,
}

/** 开着第二因子后本机被踢到哪里——那句提示只有登录页会显示，所以必须真跳过去。 */
function LocationProbe() {
  return <span data-testid="path">{useLocation().pathname}</span>
}

function renderAdminAs(overrides: Record<string, unknown>) {
  const endSession = vi.fn()
  vi.mocked(useAuth).mockReturnValue({
    session: ADMIN_SESSION,
    status: 'authenticated',
    changePassword: vi.fn(),
    logout: vi.fn(),
    endSession,
    ...overrides,
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(api.listProjects).mockResolvedValue([])
  render(<MemoryRouter><AccountPage /><LocationProbe /></MemoryRouter>)
  return endSession
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('changes the current account password without persisting password fields', async () => {
  const changePassword = vi.fn().mockResolvedValue(undefined)
  vi.mocked(useAuth).mockReturnValue({
    session: {
      token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', role: 'user', roleVerified: true, expiresAt: Date.now() + 60_000,
    },
    changePassword,
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(api.listProjects).mockResolvedValue([])

  render(<MemoryRouter><AccountPage /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'old password value' } })
  fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'new password value 1' } })
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'new password value 1' } })
  fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

  await waitFor(() => expect(changePassword).toHaveBeenCalledWith('old password value', 'new password value 1'))
  expect(localStorage.getItem('myink.password')).toBeNull()
})

it('rejects a new password without both an ASCII letter and digit', () => {
  const changePassword = vi.fn()
  vi.mocked(useAuth).mockReturnValue({
    session: {
      token: 'token-a', userId: 'user-a', username: 'alice', tier: 'normal', role: 'user', roleVerified: true,
      expiresAt: Date.now() + 60_000,
    },
    changePassword,
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(api.listProjects).mockResolvedValue([])

  render(<MemoryRouter><AccountPage /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'oldpass' } })
  fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'abcdefgh' } })
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'abcdefgh' } })
  fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

  expect(screen.getByRole('alert').textContent).toContain('ASCII 字母和 1 个 ASCII 数字')
  expect(changePassword).not.toHaveBeenCalled()
})

it('offers the admin console only to a verified administrator', () => {
  vi.mocked(api.mfaStatus).mockResolvedValue({ enabled: false })
  renderAdminAs({})

  expect(screen.getByRole('link', { name: '打开管理后台' }).getAttribute('href')).toBe('/admin')
})

it('hides the second factor from non-administrators', () => {
  vi.mocked(useAuth).mockReturnValue({
    session: { ...ADMIN_SESSION, role: 'user' },
    status: 'authenticated',
    changePassword: vi.fn(),
    logout: vi.fn(),
    endSession: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>)
  vi.mocked(api.listProjects).mockResolvedValue([])

  render(<MemoryRouter><AccountPage /></MemoryRouter>)

  expect(screen.queryByRole('heading', { name: '两步验证' })).toBeNull()
  expect(api.mfaStatus).not.toHaveBeenCalled()
})

it('enrolls a second factor after re-checking the account password', async () => {
  vi.mocked(api.mfaStatus).mockResolvedValue({ enabled: false })
  vi.mocked(api.mfaEnroll).mockResolvedValue({
    secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/Myink:root?secret=JBSWY3DPEHPK3PXP',
  })
  renderAdminAs({})

  fireEvent.change(await screen.findByLabelText('账号密码'), { target: { value: 'current password value' } })
  fireEvent.click(screen.getByRole('button', { name: '开启两步验证' }))

  expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeTruthy()
  expect(api.mfaEnroll).toHaveBeenCalledWith('current password value', 'token-a')
  // 待确认的密钥只该在本页显示，不能顺手写进 localStorage——本机留存等于把第二因子送人。
  expect(JSON.stringify(localStorage)).not.toContain('JBSWY3DPEHPK3PXP')
})

it('confirms enrollment with a code and drops the stale session', async () => {
  vi.mocked(api.mfaStatus).mockResolvedValue({ enabled: false })
  vi.mocked(api.mfaEnroll).mockResolvedValue({ secret: 'SECRET', otpauth_uri: 'otpauth://totp/x' })
  vi.mocked(api.mfaConfirm).mockResolvedValue({ ok: true })
  const endSession = renderAdminAs({})

  fireEvent.change(await screen.findByLabelText('账号密码'), { target: { value: 'pw' } })
  fireEvent.click(screen.getByRole('button', { name: '开启两步验证' }))
  fireEvent.change(await screen.findByLabelText('验证码'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: '确认开启' }))

  await waitFor(() => expect(api.mfaConfirm).toHaveBeenCalledWith('123456', 'token-a'))
  // 开启会自增 auth_version，服务端把本机这张令牌一并作废了——本机必须跟着退，否则界面
  // 还显示着登录态，而每个请求都已经是 401。
  await waitFor(() => expect(endSession).toHaveBeenCalled())
  // 还得站到登录页上：留在本页只会被 GuestShell 接管，那句提示一个字都看不到。
  // 跳转落在 endSession 之后的一拍，所以这句要重试读，读一次会偶发拿到 '/'.
  await waitFor(() => expect(screen.getByTestId('path').textContent).toBe('/login'))
})

it('keeps the session when the confirmation code is rejected', async () => {
  vi.mocked(api.mfaStatus).mockResolvedValue({ enabled: false })
  vi.mocked(api.mfaEnroll).mockResolvedValue({ secret: 'SECRET', otpauth_uri: 'otpauth://totp/x' })
  vi.mocked(api.mfaConfirm).mockRejectedValue(
    Object.assign(new Error('MFA_INVALID'), { code: 'MFA_INVALID', status: 401 }),
  )
  const endSession = renderAdminAs({})

  fireEvent.change(await screen.findByLabelText('账号密码'), { target: { value: 'pw' } })
  fireEvent.click(screen.getByRole('button', { name: '开启两步验证' }))
  fireEvent.change(await screen.findByLabelText('验证码'), { target: { value: '000000' } })
  fireEvent.click(screen.getByRole('button', { name: '确认开启' }))

  expect((await screen.findByRole('alert')).textContent).toContain('验证码不正确')
  expect(endSession).not.toHaveBeenCalled()
})

it('closes an enabled second factor with a code', async () => {
  vi.mocked(api.mfaStatus).mockResolvedValue({ enabled: true })
  vi.mocked(api.mfaDisable).mockResolvedValue({ ok: true })
  const endSession = renderAdminAs({})

  fireEvent.change(await screen.findByLabelText('验证码'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: '关闭两步验证' }))

  await waitFor(() => expect(api.mfaDisable).toHaveBeenCalledWith('123456', 'token-a'))
  await waitFor(() => expect(endSession).toHaveBeenCalled())
})
