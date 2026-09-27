// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, ApiError } from '../lib/api'
import type { Feedback } from '../types'
import { FeedbackWidget } from './FeedbackWidget'

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: { ...actual.api, submitFeedback: vi.fn(), listFeedback: vi.fn() },
    fetchFeedbackAttachment: vi.fn(),
  }
})

const submitted: Feedback = {
  id: 'fb-1',
  username: '',
  category: 'bug',
  description: '生成时第 3 章卡住了',
  contact: '',
  page_url: '/long',
  status: 'open',
  attachments: [],
  created_at: '2026-09-27T10:00:00Z',
}

beforeEach(() => {
  // jsdom 不实现 object URL；上传预览会用到它
  URL.createObjectURL = vi.fn(() => 'blob:mock')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function openPanel() {
  render(<MemoryRouter initialEntries={['/long']}><FeedbackWidget /></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: '问题反馈' }))
}

it('必填校验拦住空描述，填好后带页面路径提交并在「我的反馈」里看到', async () => {
  vi.mocked(api.submitFeedback).mockResolvedValue(submitted)
  vi.mocked(api.listFeedback).mockResolvedValue({ items: [submitted] })
  openPanel()

  // 全是空白：textarea 的 required 拦不住（值非空），靠我们自己的 trim 校验
  fireEvent.change(screen.getByLabelText('问题描述'), { target: { value: '   ' } })
  fireEvent.click(screen.getByRole('button', { name: '提交' }))
  expect((await screen.findByRole('alert')).textContent).toContain('请先写下问题描述')
  expect(api.submitFeedback).not.toHaveBeenCalled()

  fireEvent.change(screen.getByLabelText('问题描述'), { target: { value: '生成时第 3 章卡住了' } })
  fireEvent.click(screen.getByRole('button', { name: '提交' }))

  await waitFor(() => expect(api.submitFeedback).toHaveBeenCalledTimes(1))
  const form = vi.mocked(api.submitFeedback).mock.calls[0][0] as FormData
  expect(form.get('description')).toBe('生成时第 3 章卡住了')
  expect(form.get('category')).toBe('bug')
  expect(form.get('page_url')).toBe('/long')

  // 提交成功后自动切到「我的反馈」并把这条拉回来
  expect(await screen.findByText('生成时第 3 章卡住了')).toBeTruthy()
  expect(api.listFeedback).toHaveBeenCalled()
})

it('提交失败时保留已填内容并给出提示', async () => {
  vi.mocked(api.submitFeedback).mockRejectedValue(new ApiError(400, 'TOO_MANY_FILES: 最多 4 个附件', null))
  openPanel()

  fireEvent.change(screen.getByLabelText('问题描述'), { target: { value: '传了太多附件' } })
  fireEvent.click(screen.getByRole('button', { name: '提交' }))

  expect((await screen.findByRole('alert')).textContent).toContain('最多 4 个附件')
  expect((screen.getByLabelText('问题描述') as HTMLTextAreaElement).value).toBe('传了太多附件')
})

it('按 mime 与体积在客户端先拦一道', async () => {
  openPanel()
  const input = screen.getByLabelText('上传图片或视频')

  fireEvent.change(input, {
    target: { files: [new File([new Uint8Array(4)], 'x.exe', { type: 'application/x-msdownload' })] },
  })
  expect((await screen.findByRole('alert')).textContent).toContain('只支持 jpg / png / webp / gif')

  fireEvent.change(input, {
    target: {
      files: [new File([new Uint8Array(11 * 1024 * 1024)], 'big.png', { type: 'image/png' })],
    },
  })
  expect((await screen.findByRole('alert')).textContent).toContain('单张图片不要超过 10 MB')
})

it('「我的反馈」列出本人历史并显示附件取件入口', async () => {
  vi.mocked(api.listFeedback).mockResolvedValue({
    items: [{ ...submitted, status: 'resolved', attachments: [
      { index: 0, name: '现场截图.png', mime: 'image/png', bytes: 2048 },
    ] }],
  })
  openPanel()

  fireEvent.click(screen.getByRole('button', { name: '我的反馈' }))

  expect(await screen.findByText('生成时第 3 章卡住了')).toBeTruthy()
  expect(screen.getByText('已解决')).toBeTruthy()
  expect(screen.getByRole('button', { name: /现场截图\.png/ })).toBeTruthy()
})
