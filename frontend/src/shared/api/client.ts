import {
  ApiHttpError,
  ApiNetworkError,
  ApiParseError,
  type FastApiDetail,
} from './errors'

export interface ApiClientOptions {
  /** 覆盖默认 base URL（测试注入用） */
  baseUrl?: string
  fetchImpl?: typeof fetch
}

function resolveBaseUrl(override?: string): string {
  if (override !== undefined) {
    return override.replace(/\/$/, '')
  }
  const fromEnv = import.meta.env.VITE_API_BASE_URL as string | undefined
  // 缺省走 /api，配合 Vite 代理；生产也可直接指向后端根路径
  return (fromEnv ?? '/api').replace(/\/$/, '')
}

function joinUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path
  }
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${baseUrl}${normalized}`
}

/**
 * 对 path 中的动态段做 encodeURIComponent。
 * 静态前缀保持原样，避免二次编码斜杠。
 */
export function encodePath(segments: Array<string | number>): string {
  return (
    '/' +
    segments
      .map((seg) => encodeURIComponent(String(seg)).replace(/%2F/gi, '%2F'))
      .join('/')
  )
}

async function readBodyText(response: Response): Promise<string> {
  try {
    return await response.text()
  } catch (cause) {
    throw new ApiParseError(
      cause instanceof Error ? cause.message : '无法读取响应体',
      '',
    )
  }
}

function parseDetail(payload: unknown): FastApiDetail | null {
  if (payload === null || payload === undefined) {
    return null
  }
  if (typeof payload === 'string') {
    return payload
  }
  if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
    return (payload as { detail: FastApiDetail }).detail
  }
  return null
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: ApiClientOptions = {},
): Promise<T> {
  const baseUrl = resolveBaseUrl(options.baseUrl)
  const fetchImpl = options.fetchImpl ?? fetch
  const url = joinUrl(baseUrl, path)

  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetchImpl(url, { ...init, headers })
  } catch (cause) {
    throw new ApiNetworkError(cause)
  }

  const bodyText = await readBodyText(response)

  if (response.status === 204) {
    return undefined as T
  }

  let payload: unknown = undefined
  if (bodyText.trim()) {
    try {
      payload = JSON.parse(bodyText) as unknown
    } catch {
      if (!response.ok) {
        throw new ApiHttpError(response.status, null, bodyText)
      }
      throw new ApiParseError('响应不是合法 JSON', bodyText)
    }
  }

  if (!response.ok) {
    throw new ApiHttpError(response.status, parseDetail(payload), bodyText)
  }

  return payload as T
}

export const apiClient = {
  get: <T>(path: string, options?: ApiClientOptions) =>
    apiRequest<T>(path, { method: 'GET' }, options),
  post: <T>(path: string, body?: unknown, options?: ApiClientOptions) =>
    apiRequest<T>(
      path,
      { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) },
      options,
    ),
  put: <T>(path: string, body?: unknown, options?: ApiClientOptions) =>
    apiRequest<T>(
      path,
      { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) },
      options,
    ),
  delete: <T>(path: string, options?: ApiClientOptions) =>
    apiRequest<T>(path, { method: 'DELETE' }, options),
}
