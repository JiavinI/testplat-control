import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Descriptions,
  Drawer,
  Select,
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
  isRunnableCaseAsset,
  useAssetDetails,
  useAssetsTree,
  type AssetNode,
} from '@/features/assets'
import {
  ApiExecutionPanel,
  CaseExecutionPanel,
  CaseMetaPanel,
  ExecutionHistory,
} from '@/features/executions'
import { useCaseAssetDetail } from '@/features/executions/hooks'
import { useProject } from '@/features/projects/hooks'
import { joinProjectId } from '@/shared/project/ids'
import { shortSha } from '@/shared/project/display'
import {
  resolveInitialEnv,
  writePreferredEnv,
} from '@/shared/project/envPreference'
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
 * 项目工作台：组合资产浏览、API/Case 执行与执行历史。
 * api.* 挂动态参数面板；case.* 挂文件元信息 + 运行（步骤只来自运行/历史）。
 * Phase 4.0：环境下拉默认 default_env，选择写入 localStorage；运行必带 env。
 */
export function ProjectWorkspacePage() {
  const { repo = '', project: projectKey = '' } = useParams()
  const projectId = repo && projectKey ? joinProjectId(repo, projectKey) : ''
  const projectQuery = useProject(projectId)
  const isNarrow = useIsNarrowViewport()

  const [selectedAssetId, setSelectedAssetId] = useState<string | undefined>()
  const [assetDrawerOpen, setAssetDrawerOpen] = useState(false)
  const [selectedEnv, setSelectedEnv] = useState<string | null>(null)

  // 项目切换时清空选中与抽屉，避免串数据
  useEffect(() => {
    setSelectedAssetId(undefined)
    setAssetDrawerOpen(false)
    setSelectedEnv(null)
  }, [projectId])

  // 项目加载后解析初始环境（localStorage → default_env → envs[0]）
  useEffect(() => {
    if (!projectQuery.data) {
      return
    }
    setSelectedEnv(
      resolveInitialEnv(
        projectQuery.data.id,
        projectQuery.data.envs,
        projectQuery.data.default_env,
      ),
    )
  }, [projectQuery.data])

  const treeQuery = useAssetsTree(projectId)

  const selectedFromTree = useMemo(() => {
    if (!treeQuery.data || !selectedAssetId) {
      return null
    }
    return findAssetById(treeQuery.data, selectedAssetId)
  }, [treeQuery.data, selectedAssetId])

  const isCase =
    selectedFromTree !== null && isRunnableCaseAsset(selectedFromTree)
  const isApi =
    selectedFromTree !== null && isRunnableApiAsset(selectedFromTree)

  const shouldFetchApiDetails = Boolean(
    selectedFromTree && selectedFromTree.type === 'file' && !isCase,
  )
  const detailsQuery = useAssetDetails(
    projectId,
    selectedFromTree?.type === 'file' && !isCase
      ? selectedFromTree.id
      : undefined,
    shouldFetchApiDetails,
  )

  const caseDetailQuery = useCaseAssetDetail(
    projectId,
    isCase && selectedFromTree ? selectedFromTree.id : undefined,
    isCase,
  )

  const handleSelectAsset = (asset: AssetNode) => {
    setSelectedAssetId(asset.id)
    if (isNarrow) {
      setAssetDrawerOpen(false)
    }
  }

  const handleEnvChange = (env: string) => {
    setSelectedEnv(env)
    if (projectId) {
      writePreferredEnv(projectId, env)
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

  const envOptions = project.envs.map((e) => ({ value: e, label: e }))
  const canRun = Boolean(selectedEnv)

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
        {isCase && selectedFromTree ? (
          <CaseMetaPanel
            caseId={selectedFromTree.id}
            detail={caseDetailQuery.data}
            loading={caseDetailQuery.isLoading || caseDetailQuery.isFetching}
            error={caseDetailQuery.error}
            onRetry={() => {
              void caseDetailQuery.refetch()
            }}
          />
        ) : (
          <AssetDetailPanel
            selectedFromTree={selectedFromTree}
            details={detailsQuery.data}
            detailsLoading={detailsQuery.isLoading || detailsQuery.isFetching}
            detailsError={detailsQuery.error}
            onRetryDetails={() => {
              void detailsQuery.refetch()
            }}
          />
        )}
      </section>

      {!canRun && (isApi || isCase) ? (
        <Alert
          type="warning"
          showIcon
          message="请先选择运行环境"
          data-testid="workspace-env-required"
        />
      ) : null}

      {isApi && selectedFromTree && selectedEnv ? (
        <ApiExecutionPanel
          key={`${projectId}:${selectedFromTree.id}:${selectedEnv}`}
          projectId={projectId}
          assetId={selectedFromTree.id}
          env={selectedEnv}
        />
      ) : null}

      {isCase && selectedFromTree && selectedEnv ? (
        <CaseExecutionPanel
          key={`${projectId}:case:${selectedFromTree.id}:${selectedEnv}`}
          projectId={projectId}
          caseId={selectedFromTree.id}
          env={selectedEnv}
        />
      ) : null}

      {!isApi && !isCase && selectedFromTree ? (
        <Typography.Paragraph
          type="secondary"
          style={{ margin: 0 }}
          data-testid="workspace-capability-note"
        >
          {selectedFromTree.type === 'directory'
            ? '目录仅供浏览，不提供参数或运行。'
            : '当前仅 api.* 与 case.* 文件支持运行；本资产无执行面板。'}
        </Typography.Paragraph>
      ) : null}

      {!selectedFromTree ? (
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          从左侧选择资产。选中 api.* 可填参执行；选中 case.* 可查看文件元信息并运行。
        </Typography.Paragraph>
      ) : null}

      <ExecutionHistory
        projectId={projectId}
        assetId={
          selectedFromTree?.type === 'file' ? selectedFromTree.id : undefined
        }
        envs={project.envs}
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
              opacity: project.archived ? 0.55 : 1,
            }}
            title={project.name}
          >
            {project.name}
          </Typography.Title>
          <Typography.Text type="secondary" code>
            {project.id}
          </Typography.Text>
          <Typography.Text code data-testid="workspace-commit-sha">
            {shortSha(project.commit_sha)}
          </Typography.Text>
          <Select
            style={{ minWidth: 140 }}
            value={selectedEnv ?? undefined}
            options={envOptions}
            placeholder="选择环境"
            onChange={handleEnvChange}
            disabled={envOptions.length === 0}
            aria-label="运行环境"
            data-testid="workspace-env-select"
          />
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
                <Descriptions.Item label="仓库">{project.repo}</Descriptions.Item>
                <Descriptions.Item label="项目键">{project.project}</Descriptions.Item>
                <Descriptions.Item label="默认环境">
                  {project.default_env ?? '—'}
                </Descriptions.Item>
                <Descriptions.Item label="可选环境">
                  {project.envs.length ? project.envs.join(', ') : '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Commit">
                  <Typography.Text code>
                    {shortSha(project.commit_sha)}
                  </Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="归档">
                  {project.archived ? '是' : '否'}
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
