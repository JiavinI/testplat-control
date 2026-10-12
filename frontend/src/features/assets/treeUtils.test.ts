import { describe, expect, it } from 'vitest'
import type { AssetNode } from './types'
import {
  collectAssetIds,
  collectDirectoryKeys,
  filterTreeKeepingAncestors,
  findAssetById,
  isRunnableApiAsset,
  isRunnableCaseAsset,
} from './treeUtils'

const sampleTree: AssetNode = {
  id: 'assets',
  name: 'assets',
  type: 'directory',
  path: '.',
  children: [
    {
      id: 'api',
      name: 'api',
      type: 'directory',
      path: 'api',
      children: [
        {
          id: 'api.common',
          name: 'common',
          type: 'directory',
          path: 'api/common',
          children: [
            {
              id: 'api.common.health_check',
              name: 'health_check.yaml',
              type: 'file',
              path: 'api/common/health_check.yaml',
              metadata: { method: 'GET' },
            },
          ],
        },
      ],
    },
    {
      id: 'scenarios',
      name: 'scenarios',
      type: 'directory',
      path: 'scenarios',
      children: [
        {
          id: 'scenarios.login',
          name: 'login.case.yaml',
          type: 'file',
          path: 'scenarios/login.case.yaml',
        },
      ],
    },
  ],
}

describe('isRunnableApiAsset', () => {
  it('仅 api.* 文件可运行', () => {
    expect(
      isRunnableApiAsset({ id: 'api.common.health_check', type: 'file' }),
    ).toBe(true)
    expect(isRunnableApiAsset({ id: 'api', type: 'directory' })).toBe(false)
    expect(isRunnableApiAsset({ id: 'scenarios.login', type: 'file' })).toBe(false)
  })
})

describe('filterTreeKeepingAncestors', () => {
  it('空查询返回原树', () => {
    expect(filterTreeKeepingAncestors(sampleTree, '  ')).toEqual(sampleTree)
  })

  it('按文件名过滤并保留祖先路径', () => {
    const filtered = filterTreeKeepingAncestors(sampleTree, 'health_check')
    expect(filtered).not.toBeNull()
    expect(filtered!.children).toHaveLength(1)
    expect(filtered!.children![0].id).toBe('api')
    expect(filtered!.children![0].children![0].id).toBe('api.common')
    expect(filtered!.children![0].children![0].children![0].id).toBe(
      'api.common.health_check',
    )
    // scenarios 未命中，不应保留
    expect(filtered!.children!.some((c) => c.id === 'scenarios')).toBe(false)
  })

  it('按路径过滤', () => {
    const filtered = filterTreeKeepingAncestors(sampleTree, 'scenarios/')
    expect(filtered!.children).toHaveLength(1)
    expect(filtered!.children![0].id).toBe('scenarios')
  })

  it('按资产 ID 过滤', () => {
    const filtered = filterTreeKeepingAncestors(sampleTree, 'api.common.health')
    expect(findAssetById(filtered!, 'api.common.health_check')).not.toBeNull()
  })

  it('目录自身命中时保留全部子树', () => {
    const filtered = filterTreeKeepingAncestors(sampleTree, 'common')
    const common = findAssetById(filtered!, 'api.common')
    expect(common).not.toBeNull()
    expect(common!.children).toHaveLength(1)
    expect(common!.children![0].id).toBe('api.common.health_check')
  })

  it('无命中返回 null', () => {
    expect(filterTreeKeepingAncestors(sampleTree, 'zzz-not-exist')).toBeNull()
  })
})

describe('tree helpers', () => {
  it('collectAssetIds / findAssetById / collectDirectoryKeys', () => {
    const ids = collectAssetIds(sampleTree)
    expect(ids.has('api.common.health_check')).toBe(true)
    expect(ids.has('scenarios.login')).toBe(true)
    expect(findAssetById(sampleTree, 'scenarios.login')?.type).toBe('file')
    expect(collectDirectoryKeys(sampleTree)).toEqual(
      expect.arrayContaining(['assets', 'api', 'api.common', 'scenarios']),
    )
  })
})

describe('isRunnableCaseAsset', () => {
  it('仅 case.* 文件可运行', () => {
    expect(
      isRunnableCaseAsset({ id: 'case.demo.create_then_get', type: 'file' }),
    ).toBe(true)
    expect(isRunnableCaseAsset({ id: 'api.user.login', type: 'file' })).toBe(false)
    expect(isRunnableCaseAsset({ id: 'case.demo', type: 'directory' })).toBe(false)
  })
})
