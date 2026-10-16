import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiParseError } from '@/shared/api/errors'
import { getAccountCredentials, updateEnvironment } from './api'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const environment = {
  env: 'test',
  enabled: false,
  api_hosts: {},
  timeout_seconds: null,
  case_params: {},
  revision: 2,
  updated_by: 'alice',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('environments api', () => {
  it('更新环境的请求体带 revision', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(environment))
    await updateEnvironment(
      'main/gsb',
      'test',
      { revision: 1, enabled: false },
      { baseUrl: '', fetchImpl },
    )
    expect(fetchImpl.mock.calls[0][0]).toBe('/repos/main/projects/gsb/environments/test')
    const init = fetchImpl.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('PUT')
    expect(init.credentials).toBe('include')
    expect(JSON.parse(String(init.body))).toEqual({ revision: 1, enabled: false })
  })

  it('查看凭据走 no-store，解析失败不把密码放进异常正文', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        account_name: 'gsb',
        credentials: { password: 'secret-pass' },
      }),
    )
    const result = await getAccountCredentials('main/gsb', 'test', 'gsb', {
      baseUrl: '',
      fetchImpl,
    })
    expect(result.credentials.password).toBe('secret-pass')
    const init = fetchImpl.mock.calls[0][1] as RequestInit
    expect(init.cache).toBe('no-store')
    expect(String(fetchImpl.mock.calls[0][0])).toContain('/accounts/gsb/credentials')

    const broken = vi.fn().mockResolvedValue(
      jsonResponse({ account_name: 'gsb', credentials: { password: 1 } }),
    )
    await expect(
      getAccountCredentials('main/gsb', 'test', 'gsb', { baseUrl: '', fetchImpl: broken }),
    ).rejects.toSatisfy((error: unknown) => {
      expect(error).toBeInstanceOf(ApiParseError)
      const parseError = error as ApiParseError
      expect(parseError.message).not.toContain('secret')
      expect(parseError.bodyText).toBe('[已省略]')
      return true
    })
  })
})
