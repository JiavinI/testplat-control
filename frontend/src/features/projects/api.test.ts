import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createProject,
  deleteProject,
  getProject,
  listProjects,
  updateProject,
} from './api'
import type { ProjectResponse } from '@/shared/types/project'
import { ApiHttpError } from '@/shared/api/errors'

const sample: ProjectResponse = {
  id: 'p-1',
  name: 'demo',
  env: 'test',
  assets_root: '/assets',
  config_root: '/config',
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

describe('projects api', () => {
  it('listProjects 调用 GET /projects', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([sample]))
    const result = await listProjects({ baseUrl: '/api', fetchImpl })
    expect(result).toEqual([sample])
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/projects',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('getProject 对 id 编码', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(sample))
    await getProject('a/b', { baseUrl: '', fetchImpl })
    expect(fetchImpl.mock.calls[0][0]).toBe('/projects/a%2Fb')
  })

  it('createProject 提交 ProjectCreate 字段', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(sample))
    const payload = {
      name: 'demo',
      env: 'test',
      assets_root: '/assets',
      config_root: '/config',
    }
    const result = await createProject(payload, { baseUrl: '', fetchImpl })
    expect(result.id).toBe('p-1')
    const body = JSON.parse(String(fetchImpl.mock.calls[0][1].body)) as typeof payload
    expect(body).toEqual(payload)
  })

  it('updateProject 使用 PUT', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ ...sample, name: 'renamed' }),
    )
    const result = await updateProject(
      'p-1',
      { name: 'renamed' },
      { baseUrl: '', fetchImpl },
    )
    expect(result.name).toBe('renamed')
    expect(fetchImpl.mock.calls[0][0]).toBe('/projects/p-1')
    expect(fetchImpl.mock.calls[0][1].method).toBe('PUT')
  })

  it('deleteProject 成功返回 message', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ message: 'Project deleted successfully' }))
    const result = await deleteProject('p-1', { baseUrl: '', fetchImpl })
    expect(result.message).toBe('Project deleted successfully')
    expect(fetchImpl.mock.calls[0][1].method).toBe('DELETE')
  })

  it('deleteProject 404 抛出 ApiHttpError', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Project not found' }, 404))
    await expect(deleteProject('missing', { baseUrl: '', fetchImpl })).rejects.toBeInstanceOf(
      ApiHttpError,
    )
  })
})
