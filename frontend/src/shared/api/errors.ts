/** FastAPI 校验错误单项（detail 为数组时） */
export interface FastApiValidationItem {
  loc?: Array<string | number>
  msg?: string
  type?: string
  input?: unknown
  ctx?: Record<string, unknown>
}

export type FastApiDetail = string | FastApiValidationItem[] | Record<string, unknown>

/** HTTP 非 2xx：保留 status 与已解析的 FastAPI detail */
export class ApiHttpError extends Error {
  readonly kind = 'http' as const
  readonly status: number
  readonly detail: FastApiDetail | null
  readonly bodyText: string

  constructor(status: number, detail: FastApiDetail | null, bodyText: string) {
    super(formatHttpMessage(status, detail, bodyText))
    this.name = 'ApiHttpError'
    this.status = status
    this.detail = detail
    this.bodyText = bodyText
  }
}

/** 网络层失败（断网、DNS、请求被取消等） */
export class ApiNetworkError extends Error {
  readonly kind = 'network' as const
  readonly cause: unknown

  constructor(cause: unknown) {
    super(cause instanceof Error ? cause.message : '网络请求失败')
    this.name = 'ApiNetworkError'
    this.cause = cause
  }
}

/** 响应体无法按预期解析（非 JSON / 结构不符） */
export class ApiParseError extends Error {
  readonly kind = 'parse' as const
  readonly bodyText: string

  constructor(message: string, bodyText: string) {
    super(message)
    this.name = 'ApiParseError'
    this.bodyText = bodyText
  }
}

export type ApiError = ApiHttpError | ApiNetworkError | ApiParseError

export function isApiError(error: unknown): error is ApiError {
  return (
    error instanceof ApiHttpError ||
    error instanceof ApiNetworkError ||
    error instanceof ApiParseError
  )
}

function formatHttpMessage(
  status: number,
  detail: FastApiDetail | null,
  bodyText: string,
): string {
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc)
          ? item.loc.filter((p) => p !== 'body').join('.')
          : ''
        const msg = item.msg ?? '校验失败'
        return field ? `${field}: ${msg}` : msg
      })
      .join('; ')
  }
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const maybeMsg = (detail as { message?: unknown }).message
    if (typeof maybeMsg === 'string' && maybeMsg.trim()) {
      return maybeMsg
    }
  }
  return bodyText.trim() || `请求失败（HTTP ${status}）`
}

/**
 * 从 FastAPI detail 提取面向表单字段的错误文案。
 * loc 形如 ["body","name"]，取最后一个字符串段作为字段名。
 */
export function fieldErrorsFromDetail(
  detail: FastApiDetail | null | undefined,
): Record<string, string> {
  if (!Array.isArray(detail)) {
    return {}
  }
  const result: Record<string, string> = {}
  for (const item of detail) {
    if (!Array.isArray(item.loc) || item.loc.length === 0) {
      continue
    }
    const field = [...item.loc].reverse().find((p) => typeof p === 'string')
    if (typeof field !== 'string' || field === 'body') {
      continue
    }
    if (!result[field]) {
      result[field] = item.msg ?? '校验失败'
    }
  }
  return result
}
