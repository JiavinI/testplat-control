import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { getAssetDetails, getAssetsTree } from './api'
import type { AssetDetails, AssetNode } from './types'

export const assetKeys = {
  all: ['assets'] as const,
  tree: (projectId: string) => [...assetKeys.all, 'tree', projectId] as const,
  detail: (projectId: string, assetId: string) =>
    [...assetKeys.all, 'detail', projectId, assetId] as const,
}

export function useAssetsTree(
  projectId: string,
): UseQueryResult<AssetNode, Error> {
  return useQuery({
    queryKey: assetKeys.tree(projectId),
    queryFn: () => getAssetsTree(projectId),
    enabled: Boolean(projectId),
  })
}

export function useAssetDetails(
  projectId: string,
  assetId: string | undefined,
  enabled: boolean,
): UseQueryResult<AssetDetails, Error> {
  return useQuery({
    queryKey: assetKeys.detail(projectId, assetId ?? ''),
    queryFn: () => getAssetDetails(projectId, assetId!),
    enabled: Boolean(projectId) && Boolean(assetId) && enabled,
  })
}
