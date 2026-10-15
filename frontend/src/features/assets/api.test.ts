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

describe('assets api (Phase 4.0 两段式)', () => {
  it('getAssetsTree 调用 /repos/{repo}/projects/{project}/assets', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(tree))
    const result = await getAssetsTree('main/demo', { baseUrl: '/api', fetchImpl })
    expect(result.id).toBe('assets')
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/repos/main/projects/demo/assets',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('getAssetDetails 对 repo/project/assetId 分别编码', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(details))
    await getAssetDetails('main/demo', 'api.common.health_check', {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[0][0]).toBe(
      '/repos/main/projects/demo/assets/api.common.health_check',
    )
  })

  it('404 抛出 ApiHttpError', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Project not found' }, 404))
    await expect(
      getAssetsTree('main/missing', { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiHttpError)
  })
})
