import { afterEach, describe, expect, it, vi } from 'vitest'
import { getProject, listProjects } from './api'
import type { ProjectResponse } from '@/shared/types/project'
import { ApiHttpError } from '@/shared/api/errors'

const sample: ProjectResponse = {
  id: 'main/demo',
  repo: 'main',
  project: 'demo',
  name: 'demo',
  envs: ['test', 'staging'],
  default_env: 'test',
  archived: false,
  commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
  created_at: '2026-10-10T00:00:00',
  updated_at: '2026-10-10T01:00:00',
}

afterEach(() => {
  vi.restoreAllMocks()
})

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('projects api (Phase 4.0)', () => {
  it('listProjects 调用 GET /projects 并解析新字段', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([sample]))
    const result = await listProjects({ baseUrl: '/api', fetchImpl })
    expect(result).toEqual([sample])
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/projects',
      expect.objectContaining({ method: 'GET' }),
    )
    expect(result[0]).not.toHaveProperty('assets_root')
    expect(result[0]).not.toHaveProperty('config_root')
    expect(result[0]).not.toHaveProperty('env')
  })

  it('getProject 使用两段式 /repos/{repo}/projects/{project}', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(sample))
    await getProject('main/demo', { baseUrl: '', fetchImpl })
    expect(fetchImpl.mock.calls[0][0]).toBe('/repos/main/projects/demo')
  })

  it('旧字段 assets_root 缺失时仍可解析', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(sample))
    const result = await getProject('main/demo', { baseUrl: '', fetchImpl })
    expect(result.envs).toEqual(['test', 'staging'])
    expect(result.commit_sha?.startsWith('abcdef0')).toBe(true)
  })

  it('getProject 404 抛 ApiHttpError', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Project not found' }, 404))
    await expect(
      getProject('main/missing', { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiHttpError)
  })
})
