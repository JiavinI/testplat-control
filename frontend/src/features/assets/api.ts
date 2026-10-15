import { apiClient } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import { ApiParseError } from '@/shared/api/errors'
import { assertObject, requireString } from '@/shared/api/validate'
import { projectResourcePath } from '@/shared/project/ids'
import type { AssetDetails, AssetNode, AssetNodeType } from './types'

function parseNodeType(value: unknown, label: string): AssetNodeType {
  if (value !== 'directory' && value !== 'file') {
    throw new ApiParseError(`${label}.type 非法`, JSON.stringify(value))
  }
  return value
}

function parseAssetNode(payload: unknown, label = 'AssetNode'): AssetNode {
  assertObject(payload, label)
  const type = parseNodeType(payload.type, label)
  const node: AssetNode = {
    id: requireString(payload, 'id', label),
    name: requireString(payload, 'name', label),
    type,
    path: requireString(payload, 'path', label),
  }
  if ('children' in payload) {
    if (payload.children === null || payload.children === undefined) {
      node.children = payload.children as null | undefined
    } else if (Array.isArray(payload.children)) {
      node.children = payload.children.map((child, index) =>
        parseAssetNode(child, `${label}.children[${index}]`),
      )
    } else {
      throw new ApiParseError(`${label}.children 非法`, JSON.stringify(payload.children))
    }
  }
  if ('metadata' in payload) {
    if (
      payload.metadata === null ||
      payload.metadata === undefined ||
      (typeof payload.metadata === 'object' && !Array.isArray(payload.metadata))
    ) {
      node.metadata = payload.metadata as Record<string, unknown> | null | undefined
    } else {
      throw new ApiParseError(`${label}.metadata 非法`, JSON.stringify(payload.metadata))
    }
  }
  return node
}

function parseAssetDetails(payload: unknown): AssetDetails {
  assertObject(payload, 'AssetDetails')
  const type = parseNodeType(payload.type, 'AssetDetails')
  const details: AssetDetails = {
    id: requireString(payload, 'id', 'AssetDetails'),
    name: requireString(payload, 'name', 'AssetDetails'),
    type,
    path: requireString(payload, 'path', 'AssetDetails'),
  }
  if ('metadata' in payload) {
    if (
      payload.metadata === null ||
      payload.metadata === undefined ||
      (typeof payload.metadata === 'object' && !Array.isArray(payload.metadata))
    ) {
      details.metadata = payload.metadata as Record<string, unknown> | null | undefined
    } else {
      throw new ApiParseError('AssetDetails.metadata 非法', JSON.stringify(payload.metadata))
    }
  }
  return details
}

export async function getAssetsTree(
  projectId: string,
  options?: ApiClientOptions,
): Promise<AssetNode> {
  const payload = await apiClient.get<unknown>(
    projectResourcePath(projectId, 'assets'),
    options,
  )
  return parseAssetNode(payload, 'AssetTree')
}

export async function getAssetDetails(
  projectId: string,
  assetId: string,
  options?: ApiClientOptions,
): Promise<AssetDetails> {
  const payload = await apiClient.get<unknown>(
    projectResourcePath(projectId, 'assets', assetId),
    options,
  )
  return parseAssetDetails(payload)
}
