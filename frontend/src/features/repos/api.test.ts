import { afterEach, describe, expect, it, vi } from 'vitest'
import { listRepos, syncRepo } from './api'
import { ApiHttpError } from '@/shared/api/errors'

afterEach(() => {
  vi.restoreAllMocks()
})

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('repos api', () => {
  it('listRepos 调用 GET /repos', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          key: 'main',
          branch: 'main',
          current_sha: 'abc1234deadbeef',
          last_sync_at: '2026-10-15T01:00:00Z',
          last_sync_result: 'ok',
        },
      ]),
    )
    const result = await listRepos({ baseUrl: '/api', fetchImpl })
    expect(result[0].key).toBe('main')
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/repos')
  })

  it('syncRepo 成功返回 ok + SHA', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        repo: 'main',
        ok: true,
        category: 'ok',
        commit_sha: '1111222233334444555566667777888899990000',
      }),
    )
    const result = await syncRepo('main', { baseUrl: '', fetchImpl })
    expect(result.ok).toBe(true)
    expect(result.category).toBe('ok')
    expect(fetchImpl.mock.calls[0][0]).toBe('/repos/main/sync')
    expect(fetchImpl.mock.calls[0][1].method).toBe('POST')
  })

  it('syncRepo 失败只含类别不含 URL', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        repo: 'main',
        ok: false,
        category: 'network',
        commit_sha: 'oldsha0000000000000000000000000000000000',
      }),
    )
    const result = await syncRepo('main', { baseUrl: '', fetchImpl })
    expect(result.ok).toBe(false)
    expect(result.category).toBe('network')
    expect(JSON.stringify(result)).not.toMatch(/git@|https?:\/\//)
  })

  it('syncRepo 404 抛 ApiHttpError', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Repo not found' }, 404))
    await expect(syncRepo('nope', { baseUrl: '', fetchImpl })).rejects.toBeInstanceOf(
      ApiHttpError,
    )
  })
})
