import { FileOutlined, FolderOpenOutlined, FolderOutlined } from '@ant-design/icons'
import { Input, Tag, Tree, Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import { useMemo } from 'react'
import type { AssetNode } from './types'

interface AssetTreeProps {
  tree: AssetNode
  filterQuery: string
  onFilterQueryChange: (value: string) => void
  expandedKeys: string[]
  onExpandedKeysChange: (keys: string[]) => void
  selectedAssetId?: string
  onSelectAsset: (asset: AssetNode) => void
  findNode: (id: string) => AssetNode | null
}

function buildTreeData(node: AssetNode): DataNode {
  const isDir = node.type === 'directory'
  const title = (
    <span data-asset-id={node.id} data-asset-type={node.type}>
      {!isDir && node.id.startsWith('api.') && typeof node.metadata?.method === 'string'
        ? <Tag color={node.metadata.method === 'GET' ? 'green' : 'blue'} style={{ fontSize: 10, marginInlineEnd: 4 }}>{node.metadata.method}</Tag> : null}
      <Typography.Text
        ellipsis={{ tooltip: `${node.name} (${node.id})` }}
        style={{ maxWidth: 240 }}
      >
        {node.id.startsWith('api.') && typeof node.metadata?.name === 'string' ? node.metadata.name : node.name}
      </Typography.Text>
    </span>
  )

  return {
    key: node.id,
    title,
    icon: isDir
      ? ({ expanded }: { expanded?: boolean }) =>
          expanded ? <FolderOpenOutlined /> : <FolderOutlined />
      : <FileOutlined />,
    isLeaf: !isDir,
    selectable: true,
    children: isDir
      ? (node.children ?? []).map((child) => buildTreeData(child))
      : undefined,
  }
}

export function AssetTree({
  tree,
  filterQuery,
  onFilterQueryChange,
  expandedKeys,
  onExpandedKeysChange,
  selectedAssetId,
  onSelectAsset,
  findNode,
}: AssetTreeProps) {
  const treeData = useMemo(() => {
    // 根节点「assets」直接展开其子级作为顶层，减少多余一层点击
    const roots = tree.children ?? []
    if (roots.length > 0) {
      return roots.map((child) => buildTreeData(child))
    }
    return [buildTreeData(tree)]
  }, [tree])

  return (
    <div data-testid="asset-tree">
      <Input.Search
        allowClear
        placeholder="按名称 / 路径 / ID 过滤"
        value={filterQuery}
        onChange={(e) => onFilterQueryChange(e.target.value)}
        onSearch={(value) => onFilterQueryChange(value)}
        aria-label="过滤资产"
        style={{ marginBottom: 8 }}
      />
      <Tree
        showIcon
        blockNode
        virtual={false}
        treeData={treeData}
        expandedKeys={expandedKeys}
        selectedKeys={selectedAssetId ? [selectedAssetId] : []}
        onExpand={(keys) => {
          onExpandedKeysChange(keys.map(String))
        }}
        onSelect={(keys) => {
          const key = keys[0]
          if (key === undefined) {
            return
          }
          const id = String(key)
          const asset = findNode(id)
          if (!asset) {
            return
          }
          // 选中目录时自动展开，便于键盘/点击连续钻取
          if (asset.type === 'directory' && !expandedKeys.includes(id)) {
            onExpandedKeysChange([...expandedKeys, id])
          }
          onSelectAsset(asset)
        }}
        style={{ background: 'transparent' }}
      />
    </div>
  )
}
