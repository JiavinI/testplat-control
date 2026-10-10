import { apiClient, encodePath } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import type { AssetDetails, AssetNode } from './types'

export function getAssetsTree(
  projectId: string,
  options?: ApiClientOptions,
): Promise<AssetNode> {
  return apiClient.get<AssetNode>(
    encodePath(['projects', projectId, 'assets']),
    options,
  )
}

export function getAssetDetails(
  projectId: string,
  assetId: string,
  options?: ApiClientOptions,
): Promise<AssetDetails> {
  return apiClient.get<AssetDetails>(
    encodePath(['projects', projectId, 'assets', assetId]),
    options,
  )
}
