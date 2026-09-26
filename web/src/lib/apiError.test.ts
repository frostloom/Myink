// @vitest-environment node
import { expect, it } from 'vitest'
import { formatApiError, formatErrorText } from './apiError'
import { ApiError } from './api'

it('distinguishes busy creation and account model limits from book task limits', () => {
  expect(formatApiError(new ApiError(409, 'SESSION_BUSY', null))).toContain('建书操作正在处理')
  expect(formatApiError(new ApiError(503, 'CREATION_CAPACITY_EXCEEDED', null))).toContain('建书服务正忙')
  expect(formatApiError(new ApiError(429, 'ACCOUNT_MODEL_BUSY', null))).toContain('账号')
  expect(formatApiError(new ApiError(429, 'ACCOUNT_MODEL_QUOTA_EXCEEDED', null))).toContain('建书与文风')
})

it('maps queue codes and HTTP status to Chinese', () => {
  expect(formatApiError(new ApiError(429, 'CONCURRENCY_LIMIT', null))).toBe('本书已有进行中的任务，请稍候')
  expect(formatApiError(new ApiError(503, 'enqueue_failed', null))).toBe('写作任务没能进入队列，请稍后重试')
  expect(formatApiError(new ApiError(500, 'Internal Server Error', null))).toBe('服务器出错，请稍后重试')
  expect(formatApiError(new ApiError(500, '500', null))).toBe('服务器出错，请稍后重试')
  expect(formatApiError(new ApiError(404, 'not_found', null))).toBe('未找到相关内容')
  expect(formatErrorText('', 429)).toBe('请求过于频繁或额度已用完，请稍后再试')
  expect(formatErrorText('INVITATION_REQUIRED')).toBe('请输入邀请码')
  expect(formatErrorText('INVITATION_INVALID')).toBe('邀请码无效')
  expect(formatErrorText('INVITATION_EXPIRED')).toBe('邀请码已过期')
  expect(formatErrorText('INVITATION_REVOKED')).toBe('邀请码已被撤销')
  expect(formatErrorText('INVITATION_USED')).toBe('邀请码已用完')
})

it('maps model authentication failures to Chinese', () => {
  expect(formatErrorText(
    "Error code: 401 - {'error': {'message': 'Authentication Fails, Your api key: ****-xxx is invalid'}}",
  )).toBe('模型密钥无效。请到环境配置检查 API Key。')
})

it('keeps already-Chinese details and uses fallback for unknown errors', () => {
  expect(formatApiError(new ApiError(400, '扫榜超时须为 1–60 秒', null))).toBe('扫榜超时须为 1–60 秒')
  expect(formatApiError(new Error('boom'), '加载失败')).toBe('加载失败')
})

it('explains a committed creation session instead of a generic conflict', () => {
  // 后端 409 detail=SESSION_COMMITTED；泛化的 409 文案会劝用户「刷新后重试」，而那正好复现该状态。
  expect(formatApiError(new ApiError(409, 'SESSION_COMMITTED', null)))
    .toBe('这段建书对话已经开写过了，请点「重新开始」另起一篇')
  expect(formatApiError(new ApiError(409, 'Conflict', null))).toBe('内容已被其他人更新，请刷新后再试')
})
