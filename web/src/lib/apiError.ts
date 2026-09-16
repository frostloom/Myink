// 把网关/HTTP 错误码收成用户能读的中文。已含汉字的 detail 原样展示。
// 不 import ApiError，避免与 api.ts 循环依赖。

/** 三层闸门拒绝码（§6.11） */
export const GATE_CODES: Record<string, string> = {
  QUOTA_EXCEEDED: '今日免费额度已用完，请明天再试',
  BOOK_QUOTA_EXCEEDED: '本书当日写作额度已用完',
  CONCURRENCY_LIMIT: '本书已有进行中的任务，请稍候',
  DAILY_BUDGET_EXCEEDED: '当日全局成本预算已用完',
  BOOK_CNT_EXCEEDED: '今日新建作品数已达上限',
}

const ERROR_CODES: Record<string, string> = {
  ...GATE_CODES,
  enqueue_failed: '写作任务没能进入队列，请稍后重试',
  network_error: '网络连接失败，请检查网络后重试',
  invalid_body: '请求内容无效，请检查后重试',
  invalid_writing_mode: '写作模式无效',
  task_not_found: '任务不存在或已过期',
  python_api_unreachable: '后端服务暂时不可用，请稍后重试',
  not_found: '未找到相关内容',
  sse_stream_expired: '实时连接已过期，请刷新页面',
  sse_read_failed: '实时连接读取失败，请刷新页面',
  rate_limited: '请求过于频繁，请稍后再试',
  PLAN_VERSION_CONFLICT: '章节计划已被更新，请刷新后再试',
  DEMO_LOGIN_DISABLED: '演示登录已关闭',
  API_ERROR: '请求失败，请重试',
  Conflict: '内容已被其他人更新，请刷新后再试',
}

const STATUS_MESSAGES: Record<number, string> = {
  400: '请求无效，请检查填写内容',
  401: '登录已失效，请重新登录',
  403: '没有权限执行此操作',
  404: '未找到相关内容',
  409: '数据冲突，请刷新后重试',
  410: '该内容已失效，请刷新页面',
  422: '填写内容不符合要求',
  429: '请求过于频繁或额度已用完，请稍后再试',
  500: '服务器出错，请稍后重试',
  502: '服务暂时不可用，请稍后重试',
  503: '服务暂时不可用，请稍后重试',
  504: '服务响应超时，请稍后重试',
}

function looksLikeUserMessage(text: string): boolean {
  return /[\u4e00-\u9fff]/.test(text)
}

export function formatErrorText(
  code: string | null | undefined,
  status?: number,
  fallback = '请求失败，请重试',
): string {
  const raw = (code ?? '').trim()
  if (raw && looksLikeUserMessage(raw)) return raw
  if (raw && ERROR_CODES[raw]) return ERROR_CODES[raw]
  const numeric = Number(raw)
  if (raw && Number.isInteger(numeric) && STATUS_MESSAGES[numeric]) {
    return STATUS_MESSAGES[numeric]
  }
  if (status && STATUS_MESSAGES[status]) return STATUS_MESSAGES[status]
  if (/authentication fails|authentication_error|api key[^\n]*invalid|invalid_request_error|error code:\s*401/i.test(raw)) {
    return '模型密钥无效。请到环境配置检查 API Key。'
  }
  return fallback
}

export function formatApiError(err: unknown, fallback = '请求失败，请重试'): string {
  if (typeof err === 'object' && err !== null && 'code' in err && 'status' in err) {
    const { code, status } = err as { code: unknown; status: unknown }
    if (typeof code === 'string') {
      return formatErrorText(code, typeof status === 'number' ? status : undefined, fallback)
    }
  }
  return fallback
}
