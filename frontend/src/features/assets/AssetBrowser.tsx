import { Card, Empty, Input, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { ApiHttpError } from '@/shared/api/errors'
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/AsyncState'
import { AssetDetailPanel } from './AssetDetailPanel'
import { AssetTree } from './AssetTree'
import { useAssetDetails, useAssetsTree } from './hooks'
import type { AssetNode } from './types'
import { SECTIONS, type AssetSection } from '@/shared/project/sections'
import {
  collectDirectoryKeys,
  filterTreeKeepingAncestors,
  findAssetById,
  treeForSection,
} from './treeUtils'

export type AssetBrowserProps = {
  projectId: string
  selectedAssetId?: string
  onSelectAsset: (asset: AssetNode) => void
  /** full：树+详情；tree：仅树，供工作台左侧/抽屉挂载 */
  layout?: 'full' | 'tree'
  section?: AssetSection
}

/**
 * 只读资产工作台入口：树浏览 + 本地过滤 + 文件详情。
 * 不发起 params/run；不提供上传/编辑/删除。
 */
export function AssetBrowser({
  projectId,
  selectedAssetId,
  onSelectAsset,
  layout = 'full',
  section,
}: AssetBrowserProps) {
  const treeQuery = useAssetsTree(projectId)
  const scopedTree = useMemo(() => treeQuery.data
    ? section ? treeForSection(treeQuery.data, section) : treeQuery.data
    : null, [treeQuery.data, section])
  const [filterQuery, setFilterQuery] = useState('')
  const [expandedKeys, setExpandedKeys] = useState<string[]>([])
  const [expandedInitializedFor, setExpandedInitializedFor] = useState<string | null>(
    null,
  )

  // 项目切换时清空本地过滤与展开态，避免短暂残留上一项目的交互状态
  useEffect(() => {
    setFilterQuery('')
    setExpandedKeys([])
    setExpandedInitializedFor(null)
  }, [projectId, section])

  const filteredTree = useMemo(() => {
    if (!scopedTree) {
      return null
    }
    return filterTreeKeepingAncestors(scopedTree, filterQuery)
  }, [scopedTree, filterQuery])

  useEffect(() => {
    if (!scopedTree) {
      return
    }
    if (filterQuery.trim()) {
      if (filteredTree) {
        setExpandedKeys(collectDirectoryKeys(filteredTree))
      }
      return
    }
    // 无过滤时仅在首次加载该项目树时默认展开第一层目录
    if (expandedInitializedFor !== projectId) {
      const firstLevel = (scopedTree.children ?? [])
        .filter((n) => n.type === 'directory')
        .map((n) => n.id)
      setExpandedKeys(firstLevel)
      setExpandedInitializedFor(projectId)
    }
  }, [
    scopedTree,
    filterQuery,
    filteredTree,
    projectId,
    expandedInitializedFor,
  ])

  const selectedFromTree = useMemo(() => {
    if (!scopedTree || !selectedAssetId) {
      return null
    }
    // 新项目树尚未包含该 id 时视为未选中，防止串数据显示旧详情
    return findAssetById(scopedTree, selectedAssetId)
  }, [scopedTree, selectedAssetId])

  // 仅 full 布局且选中文件时拉取详情；tree 布局由工作台中央区负责
  const shouldFetchDetails = Boolean(
    layout === 'full' && selectedFromTree && selectedFromTree.type === 'file',
  )
  const detailsQuery = useAssetDetails(
    projectId,
    selectedFromTree?.type === 'file' ? selectedFromTree.id : undefined,
    shouldFetchDetails,
  )

  if (!projectId) {
    return <EmptyState description="缺少项目 ID" />
  }

  if (treeQuery.isLoading) {
    return <LoadingState tip="加载资产树…" />
  }

  if (treeQuery.isError) {
    const is404 =
      treeQuery.error instanceof ApiHttpError && treeQuery.error.status === 404
    return (
      <ErrorState
        title={is404 ? '项目不存在' : '加载资产树失败'}
        error={treeQuery.error}
        onRetry={() => {
          void treeQuery.refetch()
        }}
      />
    )
  }

  if (!scopedTree) {
    return (
      <ErrorState
        error={new Error('资产树为空响应')}
        onRetry={() => {
          void treeQuery.refetch()
        }}
      />
    )
  }

  const hasAnyChild = (scopedTree.children ?? []).length > 0
  if (!hasAnyChild) {
    return <EmptyState description={section ? `该项目暂无${SECTIONS[section].label}资产` : '该项目资产目录为空，无可展示节点'} />
  }

  if (filterQuery.trim() && !filteredTree) {
    return (
      <div data-testid="asset-browser">
        <Input.Search
          allowClear
          placeholder="按名称 / 路径 / ID 过滤"
          value={filterQuery}
          onChange={(e) => setFilterQuery(e.target.value)}
          aria-label="过滤资产"
          style={{ marginBottom: 8, maxWidth: 420 }}
        />
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={`未找到匹配「${filterQuery.trim()}」的资产`}
        />
      </div>
    )
  }

  const treeForDisplay = filteredTree ?? scopedTree

  const treeCard = (
    <Card
      size="small"
      title={section ? `${SECTIONS[section].label}资产` : '资产树'}
      style={
        layout === 'tree'
          ? { width: '100%' }
          : { flex: '1 1 260px', minWidth: 240, maxWidth: 420 }
      }
      styles={{ body: { padding: 12 } }}
    >
      <AssetTree
        tree={treeForDisplay}
        filterQuery={filterQuery}
        onFilterQueryChange={setFilterQuery}
        expandedKeys={expandedKeys}
        onExpandedKeysChange={setExpandedKeys}
        selectedAssetId={selectedFromTree?.id}
        onSelectAsset={onSelectAsset}
        findNode={(id) => scopedTree ? findAssetById(scopedTree, id) : null}
      />
    </Card>
  )

  if (layout === 'tree') {
    return (
      <div data-testid="asset-browser" data-layout="tree">
        {treeCard}
      </div>
    )
  }

  return (
    <div
      data-testid="asset-browser"
      data-layout="full"
      style={{
        display: 'flex',
        gap: 12,
        alignItems: 'stretch',
        minHeight: 280,
        flexWrap: 'wrap',
      }}
    >
      {treeCard}
      <Card
        size="small"
        title="资产详情"
        style={{ flex: '2 1 320px', minWidth: 260 }}
        styles={{ body: { padding: 12 } }}
        extra={
          selectedFromTree ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {selectedFromTree.type === 'file' ? '文件' : '目录'}
            </Typography.Text>
          ) : null
        }
      >
        <AssetDetailPanel
          selectedFromTree={selectedFromTree}
          details={detailsQuery.data}
          detailsLoading={detailsQuery.isLoading || detailsQuery.isFetching}
          detailsError={detailsQuery.error}
          onRetryDetails={() => {
            void detailsQuery.refetch()
          }}
        />
      </Card>
    </div>
  )
}
