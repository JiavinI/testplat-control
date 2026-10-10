import { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Collapse,
  Descriptions,
  Drawer,
  Space,
  Typography,
} from 'antd'
import {
  ArrowLeftOutlined,
  FolderOpenOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { Link, useParams } from 'react-router-dom'
import {
  AssetBrowser,
  AssetDetailPanel,
  findAssetById,
  isRunnableApiAsset,
  useAssetDetails,
  useAssetsTree,
  type AssetNode,
} from '@/features/assets'
import { ApiExecutionPanel, ExecutionHistory } from '@/features/executions'
import { useProject } from '@/features/projects/hooks'
import { ErrorState, LoadingState } from '@/shared/ui/AsyncState'

/** 窄屏用抽屉挂载资产树；jsdom stub 的 matchMedia 恒为 false，测试走桌面布局 */
function useIsNarrowViewport(query = '(max-width: 767px)'): boolean {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const update = () => setNarrow(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [query])
  return narrow
}

/**
 * 项目工作台：组合资产浏览、单 API 执行与执行历史。
 * 仅 api.* 文件挂载执行面板；目录/其他文件只读并说明能力边界。
 */
export function ProjectWorkspacePage() {
  const { projectId = '' } = useParams()
  const projectQuery = useProject(projectId)
  const isNarrow = useIsNarrowViewport()

  const [selectedAssetId, setSelectedAssetId] = useState<string | undefined>()
  const [assetDrawerOpen, setAssetDrawerOpen] = useState(false)

  // 项目切换时清空选中与抽屉，避免串数据
  useEffect(() => {
    setSelectedAssetId(undefined)
    setAssetDrawerOpen(false)
  }, [projectId])

  const treeQuery = useAssetsTree(projectId)

  const selectedFromTree = useMemo(() => {
    if (!treeQuery.data || !selectedAssetId) {
      return null
    }
    return findAssetById(treeQuery.data, selectedAssetId)
  }, [treeQuery.data, selectedAssetId])

  const shouldFetchDetails = Boolean(
    selectedFromTree && selectedFromTree.type === 'file',
  )
  const detailsQuery = useAssetDetails(
    projectId,
    selectedFromTree?.type === 'file' ? selectedFromTree.id : undefined,
    shouldFetchDetails,
  )

  const runnable =
    selectedFromTree !== null && isRunnableApiAsset(selectedFromTree)

  const handleSelectAsset = (asset: AssetNode) => {
    setSelectedAssetId(asset.id)
    if (isNarrow) {
      setAssetDrawerOpen(false)
    }
  }

  if (projectQuery.isLoading) {
    return <LoadingState tip="加载项目…" />
  }

  if (projectQuery.isError) {
    return (
      <div>
        <Space style={{ marginBottom: 16 }}>
          <Link to="/projects">
            <Button icon={<ArrowLeftOutlined />}>返回项目列表</Button>
          </Link>
        </Space>
        <ErrorState
          error={projectQuery.error}
          onRetry={() => {
            void projectQuery.refetch()
          }}
        />
      </div>
    )
  }

  const project = projectQuery.data
  if (!project) {
    return (
      <ErrorState
        error={new Error('项目不存在')}
        onRetry={() => {
          void projectQuery.refetch()
        }}
      />
    )
  }

  const browser = (
    <AssetBrowser
      projectId={projectId}
      selectedAssetId={selectedFromTree?.id}
      onSelectAsset={handleSelectAsset}
      layout="tree"
    />
  )

  const centerColumn = (
    <div
      data-testid="workspace-main"
      style={{
        flex: '1 1 360px',
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <section
        key={selectedFromTree?.id ?? 'empty'}
        data-testid="workspace-asset-meta"
        aria-label="资产元信息"
        className="tp-surface tp-pane-enter"
        style={{
          padding: 14,
        }}
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
      </section>

      {runnable && selectedFromTree ? (
        <ApiExecutionPanel
          key={`${projectId}:${selectedFromTree.id}`}
          projectId={projectId}
          assetId={selectedFromTree.id}
        />
      ) : null}

      {!runnable && selectedFromTree ? (
        <Typography.Paragraph
          type="secondary"
          style={{ margin: 0 }}
          data-testid="workspace-capability-note"
        >
          {selectedFromTree.type === 'directory'
            ? '目录仅供浏览，不提供参数或运行。'
            : '当前仅 api.* 文件支持参数与运行；本资产无执行面板。'}
        </Typography.Paragraph>
      ) : null}

      {!selectedFromTree ? (
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          从左侧选择资产。选中 api.* 文件后可在此填写参数并执行。
        </Typography.Paragraph>
      ) : null}

      <ExecutionHistory
        projectId={projectId}
        assetId={
          selectedFromTree?.type === 'file' ? selectedFromTree.id : undefined
        }
      />
    </div>
  )

  return (
    <div
      data-testid="project-workspace"
      style={{ maxWidth: '100%', overflowX: 'hidden' }}
    >
      <Space
        style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}
        align="start"
        wrap
      >
        <Space align="center" wrap>
          <Link to="/projects">
            <Button icon={<ArrowLeftOutlined />} aria-label="返回项目列表">
              返回
            </Button>
          </Link>
          <Typography.Title
            level={3}
            className="tp-page-title"
            style={{
              margin: 0,
              maxWidth: isNarrow ? 180 : 480,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={project.name}
          >
            {project.name}
          </Typography.Title>
          <Typography.Text code>{project.env}</Typography.Text>
        </Space>
        {isNarrow ? (
          <Button
            icon={<FolderOpenOutlined />}
            onClick={() => setAssetDrawerOpen(true)}
            aria-label="打开资产浏览"
          >
            资产
          </Button>
        ) : null}
      </Space>

      <Collapse
        size="small"
        style={{ marginBottom: 12 }}
        items={[
          {
            key: 'summary',
            label: (
              <Space size={8}>
                <UnorderedListOutlined />
                <span>项目摘要</span>
              </Space>
            ),
            children: (
              <Descriptions size="small" column={{ xs: 1, sm: 2 }}>
                <Descriptions.Item label="项目 ID">
                  <Typography.Text
                    copyable={{ text: project.id }}
                    code
                    style={{ wordBreak: 'break-all' }}
                  >
                    {project.id}
                  </Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="环境">{project.env}</Descriptions.Item>
                <Descriptions.Item label="资产目录" span={2}>
                  <Typography.Text code style={{ wordBreak: 'break-all' }}>
                    {project.assets_root}
                  </Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="配置目录" span={2}>
                  <Typography.Text code style={{ wordBreak: 'break-all' }}>
                    {project.config_root}
                  </Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {project.created_at}
                </Descriptions.Item>
                <Descriptions.Item label="更新时间">
                  {project.updated_at}
                </Descriptions.Item>
              </Descriptions>
            ),
          },
        ]}
      />

      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'flex-start',
          flexWrap: isNarrow ? 'wrap' : 'nowrap',
        }}
      >
        {!isNarrow ? (
          <aside
            data-testid="workspace-assets-aside"
            aria-label="资产浏览"
            className="tp-surface"
            style={{
              flex: '0 0 300px',
              maxWidth: 360,
              minWidth: 240,
              position: 'sticky',
              top: 8,
              alignSelf: 'flex-start',
              maxHeight: 'calc(100vh - 120px)',
              overflow: 'auto',
              padding: 10,
            }}
          >
            {browser}
          </aside>
        ) : null}

        {centerColumn}
      </div>

      <Drawer
        title="资产浏览"
        placement="left"
        width={Math.min(360, typeof window !== 'undefined' ? window.innerWidth - 24 : 360)}
        open={isNarrow && assetDrawerOpen}
        onClose={() => setAssetDrawerOpen(false)}
        destroyOnClose={false}
      >
        {browser}
      </Drawer>
    </div>
  )
}
