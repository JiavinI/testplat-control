import type { AssetNode } from './types'

/** 当前仅 api.* 文件具备 params/run 契约（目录与其它文件不可运行） */
export function isRunnableApiAsset(asset: Pick<AssetNode, 'id' | 'type'>): boolean {
  return asset.type === 'file' && asset.id.startsWith('api.')
}

function matchesQuery(node: AssetNode, query: string): boolean {
  const q = query.toLowerCase()
  return (
    node.name.toLowerCase().includes(q) ||
    node.path.toLowerCase().includes(q) ||
    node.id.toLowerCase().includes(q)
  )
}

/**
 * 本地过滤：命中节点保留；命中时保留祖先。
 * 自身命中则保留全部子树，避免目录名匹配后看不到内容。
 */
export function filterTreeKeepingAncestors(
  node: AssetNode,
  rawQuery: string,
): AssetNode | null {
  const query = rawQuery.trim()
  if (!query) {
    return node
  }

  const selfMatch = matchesQuery(node, query)
  const children = node.children ?? null

  if (node.type === 'directory' && children && children.length > 0) {
    if (selfMatch) {
      return node
    }
    const filteredChildren = children
      .map((child) => filterTreeKeepingAncestors(child, query))
      .filter((child): child is AssetNode => child !== null)
    if (filteredChildren.length === 0) {
      return null
    }
    return { ...node, children: filteredChildren }
  }

  return selfMatch ? node : null
}

/** 收集树中全部节点 id，供查找与切换校验 */
export function collectAssetIds(node: AssetNode): Set<string> {
  const ids = new Set<string>()
  const walk = (n: AssetNode) => {
    ids.add(n.id)
    for (const child of n.children ?? []) {
      walk(child)
    }
  }
  walk(node)
  return ids
}

export function findAssetById(node: AssetNode, assetId: string): AssetNode | null {
  if (node.id === assetId) {
    return node
  }
  for (const child of node.children ?? []) {
    const found = findAssetById(child, assetId)
    if (found) {
      return found
    }
  }
  return null
}

/** 过滤后自动展开所有仍存在的目录，便于看到命中路径 */
export function collectDirectoryKeys(node: AssetNode): string[] {
  const keys: string[] = []
  const walk = (n: AssetNode) => {
    if (n.type === 'directory') {
      keys.push(n.id)
      for (const child of n.children ?? []) {
        walk(child)
      }
    }
  }
  walk(node)
  return keys
}
