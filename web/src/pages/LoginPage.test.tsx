// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { useAuth } from '../context/AuthContext'
import LoginPage from './LoginPage'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('requires matching registration passwords before submitting credentials', () => {
  const register = vi.fn()
  vi.mocked(useAuth).mockReturnValue({ register } as unknown as ReturnType<typeof useAuth>)
  render(<MemoryRouter><LoginPage /></MemoryRouter>)

  fireEvent.click(screen.getByRole('tab', { name: '注册账号' }))
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'Alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'correct horse battery 1' } })
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'different password 2' } })
  fireEvent.click(screen.getByRole('button', { name: '创建账号' }))

  expect(screen.getByText('两次输入的密码不一致')).toBeTruthy()
  expect(register).not.toHaveBeenCalled()
})

it('shows an invitation only for registration and submits it without storing it', async () => {
  const register = vi.fn().mockResolvedValue(false)
  vi.mocked(useAuth).mockReturnValue({ register } as unknown as ReturnType<typeof useAuth>)
  render(<MemoryRouter><LoginPage /></MemoryRouter>)

  expect(screen.queryByLabelText('邀请码')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: '注册账号' }))
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'Alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'correct horse battery 1' } })
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'correct horse battery 1' } })
  fireEvent.change(screen.getByLabelText('邀请码'), { target: { value: '  invitation-secret  ' } })
  fireEvent.click(screen.getByRole('button', { name: '创建账号' }))

  await screen.findByRole('button', { name: '创建账号' })
  expect(register).toHaveBeenCalledWith('alice', 'correct horse battery 1', 'invitation-secret')
  expect(JSON.stringify(localStorage)).not.toContain('invitation-secret')

  fireEvent.click(screen.getByRole('tab', { name: '登录' }))
  expect(screen.queryByLabelText('邀请码')).toBeNull()
})

it('requires an invitation before registration submission', () => {
  const register = vi.fn()
  vi.mocked(useAuth).mockReturnValue({ register } as unknown as ReturnType<typeof useAuth>)
  render(<MemoryRouter><LoginPage /></MemoryRouter>)

  fireEvent.click(screen.getByRole('tab', { name: '注册账号' }))
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'Alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'correct horse battery 1' } })
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'correct horse battery 1' } })
  fireEvent.click(screen.getByRole('button', { name: '创建账号' }))

  expect(screen.getByText('请输入邀请码')).toBeTruthy()
  expect(register).not.toHaveBeenCalled()
})

it('rejects Unicode characters that case-fold into ASCII usernames', () => {
  const login = vi.fn()
  vi.mocked(useAuth).mockReturnValue({ login } as unknown as ReturnType<typeof useAuth>)
  render(<MemoryRouter><LoginPage /></MemoryRouter>)

  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'Kaa' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'correct horse battery' } })
  fireEvent.click(screen.getByRole('button', { name: '登录' }))

  expect(screen.getByText('用户名需为 3–64 位英文字母、数字、下划线或短横线')).toBeTruthy()
  expect(login).not.toHaveBeenCalled()
})

it('allows a legacy short password for login without applying new-password rules', async () => {
  const login = vi.fn().mockResolvedValue(false)
  vi.mocked(useAuth).mockReturnValue({ login } as unknown as ReturnType<typeof useAuth>)
  render(<MemoryRouter><LoginPage /></MemoryRouter>)

  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'Alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'oldpass' } })
  fireEvent.click(screen.getByRole('button', { name: '登录' }))

  await screen.findByRole('button', { name: '登录' })
  expect(login).toHaveBeenCalledWith('alice', 'oldpass')
})

it('requires an ASCII letter and digit in an eight-character registration password', async () => {
  const register = vi.fn().mockResolvedValue(false)
  vi.mocked(useAuth).mockReturnValue({ register } as unknown as ReturnType<typeof useAuth>)
  render(<MemoryRouter><LoginPage /></MemoryRouter>)

  fireEvent.click(screen.getByRole('tab', { name: '注册账号' }))
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'Alice' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'abcdefgh' } })
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'abcdefgh' } })
  fireEvent.change(screen.getByLabelText('邀请码'), { target: { value: 'invite' } })
  fireEvent.click(screen.getByRole('button', { name: '创建账号' }))
  expect(screen.getByRole('alert').textContent).toContain('ASCII 字母和 1 个 ASCII 数字')
  expect(register).not.toHaveBeenCalled()

  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'abcd1234' } })
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'abcd1234' } })
  fireEvent.click(screen.getByRole('button', { name: '创建账号' }))
  await screen.findByRole('button', { name: '创建账号' })
  expect(register).toHaveBeenCalledWith('alice', 'abcd1234', 'invite')
})

/** 走到第二步：登录回的是挑战票，页面切到验证码表单。 */
async function renderCodeStep(completeMfa: ReturnType<typeof vi.fn>) {
  const login = vi.fn().mockResolvedValue({ status: 'mfa', mfaToken: 'challenge-a' })
  vi.mocked(useAuth).mockReturnValue({ login, completeMfa } as unknown as ReturnType<typeof useAuth>)
  render(<MemoryRouter><LoginPage /></MemoryRouter>)

  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'root' } })
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'correct horse battery' } })
  fireEvent.click(screen.getByRole('button', { name: '登录' }))
  await screen.findByRole('button', { name: '验证' })
  return login
}

it('opens a code step when the password alone is not enough', async () => {
  const completeMfa = vi.fn()
  const login = await renderCodeStep(completeMfa)

  expect(login).toHaveBeenCalledWith('root', 'correct horse battery')
  // 密码对了但票还没换成令牌：这一步不该自作主张去验码，也不该留着密码框让人重复提交。
  expect(completeMfa).not.toHaveBeenCalled()
  expect(screen.queryByLabelText('密码')).toBeNull()
})

it('rejects a code that is not six digits without calling the server', async () => {
  const completeMfa = vi.fn()
  await renderCodeStep(completeMfa)

  fireEvent.change(screen.getByLabelText('验证码'), { target: { value: '12345' } })
  fireEvent.click(screen.getByRole('button', { name: '验证' }))

  expect(screen.getByRole('alert').textContent).toContain('6 位验证码')
  expect(completeMfa).not.toHaveBeenCalled()
})

it('exchanges the challenge ticket and the typed code for a session', async () => {
  const completeMfa = vi.fn().mockResolvedValue(true)
  await renderCodeStep(completeMfa)

  fireEvent.change(screen.getByLabelText('验证码'), { target: { value: ' 123456 ' } })
  fireEvent.click(screen.getByRole('button', { name: '验证' }))

  await waitFor(() => expect(completeMfa).toHaveBeenCalledWith('challenge-a', '123456'))
})

it('surfaces a rejected code without leaving the code step', async () => {
  const completeMfa = vi.fn().mockRejectedValue(
    Object.assign(new Error('MFA_INVALID'), { code: 'MFA_INVALID', status: 401 }),
  )
  await renderCodeStep(completeMfa)

  fireEvent.change(screen.getByLabelText('验证码'), { target: { value: '000000' } })
  fireEvent.click(screen.getByRole('button', { name: '验证' }))

  expect((await screen.findByRole('alert')).textContent).toContain('验证码不正确')
  expect(screen.getByLabelText('验证码')).toBeTruthy()
})

it('returns to the credential form from the code step', async () => {
  await renderCodeStep(vi.fn())

  fireEvent.click(screen.getByRole('button', { name: '返回' }))

  expect(screen.getByRole('button', { name: '登录' })).toBeTruthy()
  expect(screen.queryByLabelText('验证码')).toBeNull()
})
