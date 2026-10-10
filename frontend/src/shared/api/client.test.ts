import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient, apiRequest, encodePath } from './client'
import { ApiHttpError, ApiNetworkError, ApiParseError } from './errors'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('encodePath', () => {
  it('对动态段做 URI 编码', () => {
    expect(encodePath(['projects', 'a/b'])).toBe('/projects/a%2Fb')
    expect(encodePath(['projects', 'id with space'])).toBe(
      '/projects/id%20with%20space',
    )
  })
})

describe('apiRequest', () => {
  it('成功时解析 JSON', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const data = await apiRequest<{ ok: boolean }>('/health', {}, {
      baseUrl: '/api',
      fetchImpl,
    })

    expect(data).toEqual({ ok: true })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/health')
  })

  it('解析 FastAPI string detail 为 ApiHttpError', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Project not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(
      apiRequest('/projects/x', {}, { baseUrl: '', fetchImpl }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiHttpError)
      const httpErr = err as ApiHttpError
      expect(httpErr.status).toBe(404)
      expect(httpErr.detail).toBe('Project not found')
      expect(httpErr.message).toBe('Project not found')
      return true
    })
  })

  it('解析 FastAPI 校验数组 detail', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [
            { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
          ],
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(
      apiClient.post('/projects', {}, { baseUrl: '', fetchImpl }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiHttpError)
      const httpErr = err as ApiHttpError
      expect(httpErr.status).toBe(422)
      expect(httpErr.message).toContain('name: Field required')
      return true
    })
  })

  it('网络失败抛 ApiNetworkError', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(
      apiRequest('/projects', {}, { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiNetworkError)
  })

  it('成功响应非 JSON 抛 ApiParseError', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response('<html>oops</html>', {
        status: 200,
        headers: { 'Content-Type': 'text/html' },
      }),
    )

    await expect(
      apiRequest('/projects', {}, { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiParseError)
  })

  it('POST 自动设置 Content-Type 并序列化 body', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: '1' }), { status: 200 }),
    )

    await apiClient.post(
      '/projects',
      { name: 'demo', assets_root: '/a', config_root: '/c' },
      { baseUrl: '/api', fetchImpl },
    )

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
    expect(init.body).toBe(
      JSON.stringify({ name: 'demo', assets_root: '/a', config_root: '/c' }),
    )
  })
})
