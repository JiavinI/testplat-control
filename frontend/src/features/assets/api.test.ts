import { afterEach, describe, expect, it, vi } from 'vitest'
import { getAssetDetails, getAssetsTree } from './api'
import type { AssetDetails, AssetNode } from './types'
import { ApiHttpError } from '@/shared/api/errors'

const tree: AssetNode = {
  id: 'assets',
  name: 'assets',
  type: 'directory',
  path: '.',
  children: [],
}

const details: AssetDetails = {
  id: 'api.common.health_check',
  name: 'health_check.yaml',
  type: 'file',
  path: 'api/common/health_check.yaml',
  metadata: { method: 'GET' },
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

describe('assets api', () => {
  it('getAssetsTree 调用 GET /projects/:id/assets', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(tree))
    const result = await getAssetsTree('p-1', { baseUrl: '/api', fetchImpl })
    expect(result.id).toBe('assets')
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/projects/p-1/assets',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('getAssetDetails 对 projectId 与 assetId 编码', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(details))
    await getAssetDetails('a/b', 'api.common.health_check', {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[0][0]).toBe(
      '/projects/a%2Fb/assets/api.common.health_check',
    )
  })

  it('404 抛出 ApiHttpError', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Project not found' }, 404))
    await expect(
      getAssetsTree('missing', { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiHttpError)
  })
})
